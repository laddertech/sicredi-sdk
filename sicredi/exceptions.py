"""Hierarquia de exceções do SDK.

Toda falha levantada pelo SDK descende de :class:`SicrediError`, então quem
integra pode capturar só ela. As subclasses separam o que é corrigível pelo
chamador (parâmetro, credencial, permissão) do que é transitório (rede, 5xx).
"""

from __future__ import annotations

from typing import Any


class SicrediError(Exception):
    """Base de todas as exceções do SDK."""


class ConfiguracaoError(SicrediError):
    """Configuração local inválida (credencial ausente, certificado ilegível).

    Falha anterior à rede: repetir com a mesma configuração nunca passa.
    """


class CertificadoError(ConfiguracaoError):
    """Certificado/chave mTLS ausente, ilegível ou com senha errada."""


class ValidacaoError(SicrediError, ValueError):
    """Parâmetro inválido detectado localmente, antes de chamar a API."""


class ConexaoError(SicrediError):
    """Falha de rede (timeout, DNS, TLS) — em geral transitória."""


class ApiError(SicrediError):
    """Resposta de erro da API do Sicredi.

    Attributes:
        status_code: status HTTP devolvido.
        detail: mensagem de erro extraída do corpo, quando houver.
        body: corpo da resposta (JSON decodificado ou texto).
    """

    def __init__(
        self,
        mensagem: str,
        *,
        status_code: int | None = None,
        detail: str | None = None,
        body: Any = None,
    ) -> None:
        super().__init__(mensagem)
        self.status_code = status_code
        self.detail = detail
        self.body = body


class RequisicaoInvalidaError(ApiError):
    """HTTP 400: parâmetros recusados pela API."""


class AutenticacaoError(ApiError):
    """Falha ao obter token ou token recusado (HTTP 401)."""


class PermissaoError(ApiError):
    """HTTP 403: escopo não liberado para a credencial ou conta inválida."""


class NaoEncontradoError(ApiError):
    """HTTP 404."""


class LimiteRequisicoesError(ApiError):
    """HTTP 429: limite de requisições excedido."""


class ServidorError(ApiError):
    """HTTP 5xx: falha do lado do Sicredi — em geral transitória."""


class RespostaInvalidaError(ApiError):
    """Resposta 2xx com corpo fora do contrato esperado."""
