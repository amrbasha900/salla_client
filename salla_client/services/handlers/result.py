from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ClientApplyMessage:
    code: str
    message: str
    details: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "details": self.details,
        }


@dataclass
class ClientApplyResult:
    status: str
    erp_doctype: str | None = None
    erp_doc: str | None = None
    message: str | None = None
    warnings: list[ClientApplyMessage] = field(default_factory=list)
    errors: list[ClientApplyMessage] = field(default_factory=list)

    def add_warning(self, code: str, message: str, **details: Any) -> None:
        self.warnings.append(ClientApplyMessage(code=code, message=message, details=details))

    def add_error(self, code: str, message: str, **details: Any) -> None:
        self.errors.append(ClientApplyMessage(code=code, message=message, details=details))

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "erp_doctype": self.erp_doctype,
            "erp_doc": self.erp_doc,
            "message": self.message,
            "warnings": [warning.as_dict() for warning in self.warnings],
            "errors": [error.as_dict() for error in self.errors],
        }
