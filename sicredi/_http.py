"""Transporte HTTP com mTLS e tradução de erros (uso interno)."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import requests
from requests_pkcs12 import Pkcs12Adapter

from sicredi.certificado import Identidade
from sicredi.exceptions import (
    ApiError,
    AutenticacaoError,
    ConexaoError,
    LimiteRequisicoesError,
    NaoEncontradoError,
    PermissaoError,
    RequisicaoInvalidaError,
    RespostaInvalidaError,
    ServidorError,
)

_POR_STATUS: dict[int, type[ApiError]] = {
    400: RequisicaoInvalidaError,
    401: AutenticacaoError,
    403: PermissaoError,
    404: NaoEncontradoError,
    422: RequisicaoInvalidaError,
    429: LimiteRequisicoesError,
}


def _decodificar(resposta: requests.Response) -> Any:
    """JSON com números decimais como ``Decimal`` (nunca float para dinheiro)."""
    if not resposta.content:
        return None
    try:
        return resposta.json(parse_float=Decimal)
    except ValueError:
        return resposta.text


def _detalhe(corpo: Any) -> str | None:
    if isinstance(corpo, dict):
        for campo in ('detail', 'message', 'mensagem', 'error_description', 'title'):
            valor = corpo.get(campo)
            if valor:
                return str(valor)
        erro = corpo.get('error')
        if isinstance(erro, str) and erro:
            return erro
    elif isinstance(corpo, str) and corpo.strip():
        return corpo.strip()[:500]
    return None


def _sem_auth(requisicao: requests.PreparedRequest) -> requests.PreparedRequest:
    return requisicao


class Transporte:
    """Sessão ``requests`` própria, com o certificado mTLS montado.

    A sessão é sempre exclusiva da instância e o certificado só é montado na
    origem da API: compartilhar sessão entre clientes faria um certificado
    sobrescrever o outro, e montá-lo em ``https://`` o apresentaria a
    qualquer outro servidor que o pedisse.
    """

    def __init__(self, identidade: Identidade, timeout: float, origem: str) -> None:
        self.timeout = timeout
        self.session = requests.Session()
        # Auth nula impede o requests de aplicar credenciais do ~/.netrc, que
        # sobrescreveriam o Bearer; trust_env segue valendo para proxies.
        self.session.auth = _sem_auth
        self.session.mount(
            origem.rstrip('/') + '/',
            Pkcs12Adapter(
                pkcs12_data=identidade.pkcs12_data,
                pkcs12_password=identidade.senha,
            ),
        )

    def close(self) -> None:
        self.session.close()

    def _enviar(self, metodo: str, url: str, contexto: str, **kwargs) -> Any:
        kwargs.setdefault('timeout', self.timeout)
        # Redirecionamento poderia levar segredo/token a outro destino: a
        # API não redireciona, então qualquer 3xx é tratado como erro.
        kwargs['allow_redirects'] = False
        try:
            resposta = self.session.request(metodo, url, **kwargs)
        except requests.Timeout as exc:
            raise ConexaoError(f'Tempo esgotado ao {contexto}.') from exc
        except requests.RequestException as exc:
            raise ConexaoError(f'Falha de conexão ao {contexto}: {exc}') from exc
        corpo = _decodificar(resposta)
        status = resposta.status_code
        if 200 <= status < 300:
            return corpo
        detalhe = _detalhe(corpo)
        classe = ServidorError if status >= 500 else _POR_STATUS.get(status, ApiError)
        mensagem = f'Erro {status} ao {contexto}'
        if 300 <= status < 400:
            mensagem = f'{mensagem}: redirecionamento recusado'
        if detalhe:
            mensagem = f'{mensagem}: {detalhe}'
        raise classe(mensagem, status_code=status, detail=detalhe, body=corpo)

    def post_form(
        self,
        url: str,
        dados: dict[str, str],
        *,
        contexto: str,
    ) -> Any:
        return self._enviar(
            'POST',
            url,
            contexto,
            data=dados,
            headers={'Accept': 'application/json'},
        )

    def get_json(
        self,
        url: str,
        *,
        token: str,
        params: dict[str, Any] | None = None,
        contexto: str,
    ) -> Any:
        corpo = self._enviar(
            'GET',
            url,
            contexto,
            params=params,
            headers={
                'Authorization': f'Bearer {token}',
                'Accept': 'application/json',
            },
        )
        if not isinstance(corpo, dict):
            raise RespostaInvalidaError(
                f'Resposta inesperada ao {contexto}: JSON objeto esperado.',
                body=corpo,
            )
        return corpo
