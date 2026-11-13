"""Ambientes e URLs da API de parceiros do Sicredi.

A configuração é **por instância** de cliente — não há estado global. Dois
clientes no mesmo processo podem apontar para ambientes diferentes sem que
um contamine o outro.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from urllib.parse import urlparse

from sicredi.exceptions import ConfiguracaoError

HOST_MTLS = 'https://mtls-api-parceiro.sicredi.com.br'


class Ambiente(str, Enum):
    """Ambiente da API. O sandbox devolve dados estáticos."""

    SANDBOX = 'sandbox'
    PRODUCAO = 'producao'

    @classmethod
    def parse(cls, valor: Ambiente | str) -> Ambiente:
        """Aceita o enum ou um apelido textual (``sandbox``, ``prod``...)."""
        if isinstance(valor, Ambiente):
            return valor
        apelidos = {
            'sandbox': cls.SANDBOX,
            'sb': cls.SANDBOX,
            'homologacao': cls.SANDBOX,
            'producao': cls.PRODUCAO,
            'production': cls.PRODUCAO,
            'prod': cls.PRODUCAO,
        }
        try:
            return apelidos[str(valor).strip().lower()]
        except KeyError:
            raise ConfiguracaoError(
                f'Ambiente desconhecido: {valor!r}. Use "sandbox" ou "producao".'
            ) from None


@dataclass(frozen=True)
class Config:
    """URLs resolvidas para um ambiente.

    Args:
        ambiente: ambiente da API.
        base_url: raiz explícita da API (sobrepõe a derivada do ambiente).
            Útil para proxies ou mudanças de host sem nova versão do SDK.
        timeout: timeout padrão, em segundos, de cada requisição.
    """

    ambiente: Ambiente = Ambiente.PRODUCAO
    base_url: str | None = None
    timeout: float = 30.0

    def __post_init__(self) -> None:
        if self.base_url is not None:
            partes = urlparse(self.base_url)
            # Credenciais e tokens só trafegam sobre TLS: o mTLS é montado
            # apenas para https://, então http:// os mandaria em texto claro.
            if partes.scheme != 'https' or not partes.hostname:
                raise ConfiguracaoError(
                    f'base_url precisa ser uma URL https:// válida: {self.base_url!r}'
                )

    @property
    def raiz(self) -> str:
        """Raiz das rotas (já com o prefixo ``/sb`` no sandbox)."""
        if self.base_url:
            return self.base_url.rstrip('/')
        if self.ambiente is Ambiente.SANDBOX:
            return f'{HOST_MTLS}/sb'
        return HOST_MTLS

    @property
    def origem(self) -> str:
        """``https://host[:porta]`` da API — onde o certificado é montado."""
        partes = urlparse(self.raiz)
        return f'{partes.scheme}://{partes.netloc}'

    @property
    def token_url(self) -> str:
        return f'{self.raiz}/thirdparty/auth/token'

    def url(self, caminho: str) -> str:
        return f'{self.raiz}/{caminho.lstrip("/")}'
