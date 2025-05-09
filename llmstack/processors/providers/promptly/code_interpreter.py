import base64
import logging
import uuid
from typing import List, Optional

from asgiref.sync import async_to_sync
from django.conf import settings
from langrocks.client.code_runner import (
    CodeRunner,
    CodeRunnerSession,
    CodeRunnerState,
    Content,
    ContentMimeType,
)
from pydantic import Field

from llmstack.apps.schemas import OutputTemplate
from llmstack.common.blocks.base.schema import StrEnum
from llmstack.common.utils.utils import validate_parse_data_uri
from llmstack.processors.providers.api_processor_interface import (
    ApiProcessorInterface,
    ApiProcessorSchema,
)
from llmstack.processors.providers.promptly import Content as PromptlyContent
from llmstack.processors.providers.promptly import (
    ContentMimeType as PromptlyContentMimeType,
)

logger = logging.getLogger(__name__)


class CodeInterpreterLanguage(StrEnum):
    PYTHON = "Python"


class CodeInterpreterInput(ApiProcessorSchema):
    code: str = Field(description="The code to run", json_schema_extra={"widget": "textarea"}, default="")
    files: Optional[str] = Field(
        description="Workspace files as a comma separated list",
        default=None,
        json_schema_extra={
            "widget": "file",
        },
    )
    language: CodeInterpreterLanguage = Field(
        title="Language", description="The language of the code", default=CodeInterpreterLanguage.PYTHON
    )


class CodeInterpreterOutput(ApiProcessorSchema):
    stdout: List[PromptlyContent] = Field(default=[], description="Standard output as a list of Content objects")
    stderr: str = Field(default="", description="Standard error")
    exit_code: int = Field(default=0, description="Exit code of the process")


class CodeInterpreterConfiguration(ApiProcessorSchema):
    timeout: int = Field(default=5, description="Timeout in seconds", ge=1, le=30)


def mime_type_to_content_mime_type(mime_type):
    if mime_type == "text/plain":
        return ContentMimeType.TEXT
    if mime_type == "image/png":
        return ContentMimeType.PNG
    if mime_type == "image/jpeg":
        return ContentMimeType.JPEG
    if mime_type == "image/svg+xml":
        return ContentMimeType.SVG
    if mime_type == "application/pdf":
        return ContentMimeType.PDF
    if mime_type == "text/html":
        return ContentMimeType.HTML
    if mime_type == "application/json":
        return ContentMimeType.JSON
    if mime_type == "text/latex":
        return ContentMimeType.LATEX
    if mime_type == "text/csv":
        return ContentMimeType.CSV
    return ContentMimeType.TEXT


class CodeInterpreterProcessor(
    ApiProcessorInterface[CodeInterpreterInput, CodeInterpreterOutput, CodeInterpreterConfiguration],
):
    @staticmethod
    def name() -> str:
        return "Code Interpreter"

    @staticmethod
    def slug() -> str:
        return "code_interpreter"

    @staticmethod
    def description() -> str:
        return "Runs the provided code and returns the output"

    @staticmethod
    def provider_slug() -> str:
        return "promptly"

    @staticmethod
    def get_output_template() -> Optional[OutputTemplate]:
        return OutputTemplate(
            markdown="""{% for line in stdout %}

{% if line.mime_type == "text/plain" %}
{{ line.data }}
{% endif %}

{% if line.mime_type == "image/png" %}
![Image](data:image/png;base64,{{line.data}})
{% endif %}

{% endfor %}""",
            jsonpath="$.stdout",
        )

    def convert_stdout_to_content(self, stdout) -> List[Content]:
        from langrocks.common.models import runner_pb2

        content = []
        for entry in stdout:
            if not entry.mime_type or entry.mime_type == runner_pb2.ContentMimeType.TEXT:
                content.append(Content(mime_type=ContentMimeType.TEXT, data=entry.data.decode("utf-8")))
            elif entry.mime_type == runner_pb2.ContentMimeType.JSON:
                content.append(Content(mime_type=ContentMimeType.JSON, data=entry.data.decode("utf-8")))
            elif entry.mime_type == runner_pb2.ContentMimeType.HTML:
                content.append(Content(mime_type=ContentMimeType.HTML, data=entry.data.decode("utf-8")))
            elif entry.mime_type == runner_pb2.ContentMimeType.PNG:
                data = base64.b64encode(entry.data).decode("utf-8")
                content.append(Content(mime_type=ContentMimeType.PNG, data=data))
            elif entry.mime_type == runner_pb2.ContentMimeType.JPEG:
                data = base64.b64encode(entry.data).decode("utf-8")
                content.append(Content(mime_type=ContentMimeType.JPEG, data=data))
            elif entry.mime_type == runner_pb2.ContentMimeType.SVG:
                data = base64.b64encode(entry.data).decode("utf-8")
                content.append(Content(mime_type=ContentMimeType.SVG, data=data))
            elif entry.mime_type == runner_pb2.ContentMimeType.PDF:
                data = base64.b64encode(entry.data).decode("utf-8")
                content.append(Content(mime_type=ContentMimeType.PDF, data=data))
            elif entry.mime_type == runner_pb2.ContentMimeType.LATEX:
                data = base64.b64encode(entry.data).decode("utf-8")
                content.append(Content(mime_type=ContentMimeType.LATEX, data=data))
        return content

    def process_session_data(self, session_data):
        self._interpreter_session_id = session_data.get("interpreter_session_id", str(uuid.uuid4()))
        self._interpreter_session_data = session_data.get("interpreter_session_data", "")

    def session_data_to_persist(self) -> dict:
        return {
            "interpreter_session_id": self._interpreter_session_id,
            "interpreter_session_data": self._interpreter_session_data,
        }

    def get_file_data_uri_from_objref(self, objref):
        from llmstack.apps.models import AppSessionFiles

        asset_obj = self._get_session_asset(
            objref,
        )
        asset = AppSessionFiles.get_asset_data_uri(asset_obj, include_name=True) if asset_obj else None

        return asset

    def process(self) -> dict:
        content_files = []
        for file in self._input.files.split("|"):
            if file.startswith("objref://"):
                file = self.get_file_data_uri_from_objref(file)
            if not file:
                continue

            mime_type, file_name, data = validate_parse_data_uri(file)
            content_files.append(
                Content(
                    mime_type=mime_type_to_content_mime_type(mime_type=mime_type),
                    data=base64.b64decode(data),
                    name=file_name,
                )
            )

        with CodeRunner(
            base_url=f"{settings.RUNNER_HOST}:{settings.RUNNER_PORT}",
            session=CodeRunnerSession(
                session_id=self._interpreter_session_id, session_data=self._interpreter_session_data
            ),
        ) as code_runner:
            current_state = code_runner.get_state()
            if current_state == CodeRunnerState.CODE_RUNNING:
                respose_iter = code_runner.run_code(source_code=self._input.code, files=content_files)
                for response in respose_iter:
                    async_to_sync(self._output_stream.write)(
                        CodeInterpreterOutput(
                            stdout=[PromptlyContent(mime_type=PromptlyContentMimeType.TEXT, data=response.decode())]
                        )
                    )

            session_data = code_runner.get_session()
            self._interpreter_session_data = session_data.session_data

        output = self._output_stream.finalize()
        return output
