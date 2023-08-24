from __future__ import annotations

import json
import os
import pathlib
import sys
from typing import (
    Any,
    Optional,
)


# **********************************************************
# Update sys.path before importing any bundled libraries.
# **********************************************************

def update_sys_path(path_to_add: str, strategy: str) -> None:
    """Add given path to `sys.path`."""
    if path_to_add not in sys.path and os.path.isdir(path_to_add):
        if strategy == "useBundled":
            sys.path.insert(0, path_to_add)
        elif strategy == "fromEnvironment":
            sys.path.append(path_to_add)
        else:
            raise ValueError("unrecognized import strategy", strategy)


update_sys_path(
    os.fspath(pathlib.Path(__file__).parent.parent / "libs"),
    os.getenv("LS_IMPORT_STRATEGY", "useBundled"),
)


# **********************************************************
# Imports needed for the language server goes below this.
# **********************************************************

# pylint: disable=wrong-import-position,import-error
import lsp_jsonrpc as jsonrpc
import lsprotocol.types as lsp

from pygls import server, uris, workspace

from lsprotocol.types import (
    FoldingRange,
    FoldingRangeKind,
    FoldingRangeParams,
    CodeAction,
    CodeActionKind,
)

import maccarone

from maccarone.preprocessor import (
    PresentPiece,
    MissingPiece,
    raw_source_to_pieces,
)
from maccarone.scripts.preprocess import preprocess

WORKSPACE_SETTINGS = {}
GLOBAL_SETTINGS = {}
RUNNER = pathlib.Path(__file__).parent / "lsp_runner.py"

MAX_WORKERS = 5
LSP_SERVER = server.LanguageServer(
    name="maccarone",
    version=maccarone.__version__ + "-lsp", # not the extension version but whatever
    max_workers=MAX_WORKERS,
)


@LSP_SERVER.feature("maccarone/apply")
def apply_command(params: Any) -> dict:
    LSP_SERVER.show_message_log("applying maccarone changes " + repr(params))

    document = LSP_SERVER.workspace.get_document(params.documentUri)

    if params.blockAtLine is None:
        block_at_line = None
    else:
        block_at_line = params.blockAtLine + 1

    LSP_SERVER.show_message_log("path: " + str(document.path))

    if document.path is None:
        return {}

    preprocess(
        mn_path=document.path,
        rewrite=True,
        print_=False,
        block_at_line=block_at_line,
    )

    return {}


@LSP_SERVER.feature(lsp.TEXT_DOCUMENT_FOLDING_RANGE)
def folding(params: FoldingRangeParams) -> Optional[list[FoldingRange]]:
    document = LSP_SERVER.workspace.get_document(params.text_document.uri)
    source = document.source
    pieces = raw_source_to_pieces(source, None)
    line_num = 0
    ranges = []

    for piece in pieces:
        if isinstance(piece, PresentPiece):
            line_num += source.count("\n", piece.start, piece.end)
        elif isinstance(piece, MissingPiece):
            start_line = line_num
            line_num += source.count("\n", piece.start, piece.end)

            ranges.append((start_line, line_num - 1))
        else:
            log_warning(f"unknown type of source piece: {type(piece)}")

    return [
        FoldingRange(
            start_line=sl,
            end_line=el,
            kind=FoldingRangeKind.Region,
        )
        for (sl, el) in ranges
    ]


@LSP_SERVER.feature(lsp.TEXT_DOCUMENT_CODE_ACTION)
def code_action(ls, params: lsp.CodeActionParams):
    document = LSP_SERVER.workspace.get_document(params.text_document.uri)
    source = document.source
    pieces = raw_source_to_pieces(source, None)
    action = CodeAction(
        title="Update AI Block",
        kind=CodeActionKind.RefactorRewrite,
        command={
            "title": "Update AI Block",
            "command": "maccarone.apply",
            "arguments": [params.range.start.line],
        },
    )
    line_num = 0

    for piece in pieces:
        if isinstance(piece, PresentPiece):
            line_num += source.count("\n", piece.start, piece.end)
        elif isinstance(piece, MissingPiece):
            start_line = line_num
            line_num += source.count("\n", piece.start, piece.end)

            if start_line <= params.range.start.line <= line_num:
                return [action]
        else:
            log_warning(f"unknown type of source piece: {type(piece)}")

    return []


@LSP_SERVER.feature(lsp.INITIALIZE)
def initialize(params: lsp.InitializeParams) -> None:
    """LSP handler for initialize request."""
    log_to_output(f"CWD Server: {os.getcwd()}")

    paths = "\r\n   ".join(sys.path)
    log_to_output(f"sys.path used to run Server:\r\n   {paths}")

    GLOBAL_SETTINGS.update(**params.initialization_options.get("globalSettings", {}))

    settings = params.initialization_options["settings"]
    _update_workspace_settings(settings)
    log_to_output(
        f"Settings used to run Server:\r\n{json.dumps(settings, indent=4, ensure_ascii=False)}\r\n"
    )
    log_to_output(
        f"Global settings:\r\n{json.dumps(GLOBAL_SETTINGS, indent=4, ensure_ascii=False)}\r\n"
    )


@LSP_SERVER.feature(lsp.EXIT)
def on_exit(_params: Optional[Any] = None) -> None:
    """Handle clean up on exit."""
    jsonrpc.shutdown_json_rpc()


@LSP_SERVER.feature(lsp.SHUTDOWN)
def on_shutdown(_params: Optional[Any] = None) -> None:
    """Handle clean up on shutdown."""
    jsonrpc.shutdown_json_rpc()


def _get_global_defaults():
    return {
        "path": GLOBAL_SETTINGS.get("path", []),
        "interpreter": GLOBAL_SETTINGS.get("interpreter", [sys.executable]),
        "args": GLOBAL_SETTINGS.get("args", []),
        "importStrategy": GLOBAL_SETTINGS.get("importStrategy", "useBundled"),
        "showNotifications": GLOBAL_SETTINGS.get("showNotifications", "off"),
    }


def _update_workspace_settings(settings):
    if not settings:
        key = os.getcwd()
        WORKSPACE_SETTINGS[key] = {
            "cwd": key,
            "workspaceFS": key,
            "workspace": uris.from_fs_path(key),
            **_get_global_defaults(),
        }
        return

    for setting in settings:
        key = uris.to_fs_path(setting["workspace"])
        WORKSPACE_SETTINGS[key] = {
            **setting,
            "workspaceFS": key,
        }


def _get_settings_by_path(file_path: pathlib.Path):
    workspaces = {s["workspaceFS"] for s in WORKSPACE_SETTINGS.values()}

    while file_path != file_path.parent:
        str_file_path = str(file_path)
        if str_file_path in workspaces:
            return WORKSPACE_SETTINGS[str_file_path]
        file_path = file_path.parent

    setting_values = list(WORKSPACE_SETTINGS.values())
    return setting_values[0]


def _get_document_key(document: workspace.Document):
    if WORKSPACE_SETTINGS:
        document_workspace = pathlib.Path(document.path)
        workspaces = {s["workspaceFS"] for s in WORKSPACE_SETTINGS.values()}

        # Find workspace settings for the given file.
        while document_workspace != document_workspace.parent:
            if str(document_workspace) in workspaces:
                return str(document_workspace)
            document_workspace = document_workspace.parent

    return None


def _get_settings_by_document(document: workspace.Document | None):
    if document is None or document.path is None:
        return list(WORKSPACE_SETTINGS.values())[0]

    key = _get_document_key(document)
    if key is None:
        # This is either a non-workspace file or there is no workspace.
        key = os.fspath(pathlib.Path(document.path).parent)
        return {
            "cwd": key,
            "workspaceFS": key,
            "workspace": uris.from_fs_path(key),
            **_get_global_defaults(),
        }

    return WORKSPACE_SETTINGS[str(key)]


def log_to_output(
    message: str, msg_type: lsp.MessageType = lsp.MessageType.Log
) -> None:
    LSP_SERVER.show_message_log(message, msg_type)


def log_error(message: str) -> None:
    LSP_SERVER.show_message_log(message, lsp.MessageType.Error)
    if os.getenv("LS_SHOW_NOTIFICATION", "off") in ["onError", "onWarning", "always"]:
        LSP_SERVER.show_message(message, lsp.MessageType.Error)


def log_warning(message: str) -> None:
    LSP_SERVER.show_message_log(message, lsp.MessageType.Warning)
    if os.getenv("LS_SHOW_NOTIFICATION", "off") in ["onWarning", "always"]:
        LSP_SERVER.show_message(message, lsp.MessageType.Warning)


def log_always(message: str) -> None:
    LSP_SERVER.show_message_log(message, lsp.MessageType.Info)
    if os.getenv("LS_SHOW_NOTIFICATION", "off") in ["always"]:
        LSP_SERVER.show_message(message, lsp.MessageType.Info)


if __name__ == "__main__":
    LSP_SERVER.start_io()
