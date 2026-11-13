"""Token OAuth2 (client_credentials sobre mTLS) com cache plugável.

O cache é por **credencial + ambiente + escopo**. Isso importa para quem
atende várias contas no mesmo processo (ex.: um ERP multi-organização): o
token de uma conta nunca é servido para outra, mesmo com um
:class:`TokenStore` compartilhado (Redis, cache do Django...).
"""

from __future__ import annotations

import hashlib
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from sicredi.exceptions import RespostaInvalidaError

if TYPE_CHECKING:
    from sicredi._http import Transporte

# Renova o token um pouco antes de expirar para não usá-lo no limite.
MARGEM_RENOVACAO = 60
VALIDADE_PADRAO = 3600


@dataclass(frozen=True)
class Token:
    access_token: str = field(repr=False)
    expira_em: float  # epoch, em segundos
    token_type: str = 'Bearer'

    def valido(self, agora: float | None = None) -> bool:
        agora = time.time() if agora is None else agora
        return agora < self.expira_em - MARGEM_RENOVACAO


@runtime_checkable
class TokenStore(Protocol):
    """Armazenamento de tokens. Implemente para usar um cache compartilhado.

    ``ttl`` é o tempo de vida em segundos; quem implementa pode usá-lo para
    expirar a entrada sozinho (o SDK revalida a expiração de qualquer forma).
    """

    def get(self, chave: str) -> Token | None: ...

    def set(self, chave: str, token: Token, ttl: int) -> None: ...

    def delete(self, chave: str) -> None: ...


class MemoryTokenStore:
    """Cache em memória do processo, seguro para threads (padrão)."""

    def __init__(self) -> None:
        self._dados: dict[str, Token] = {}
        self._lock = threading.Lock()

    def get(self, chave: str) -> Token | None:
        with self._lock:
            return self._dados.get(chave)

    def set(self, chave: str, token: Token, ttl: int) -> None:
        with self._lock:
            self._dados[chave] = token

    def delete(self, chave: str) -> None:
        with self._lock:
            self._dados.pop(chave, None)


class OAuth2Client:
    """Obtém e reaproveita tokens por escopo."""

    def __init__(
        self,
        transporte: Transporte,
        client_id: str,
        client_secret: str,
        token_url: str,
        token_store: TokenStore | None = None,
        relogio: Callable[[], float] = time.time,
        certificado_fingerprint: str = '',
    ) -> None:
        self._transporte = transporte
        self._certificado = certificado_fingerprint
        self._client_id = client_id
        self._client_secret = client_secret
        self._token_url = token_url
        self._store = token_store if token_store is not None else MemoryTokenStore()
        self._relogio = relogio
        self._lock = threading.Lock()

    def _chave(self, escopo: str) -> str:
        # Secret e certificado entram no hash: rotacionar qualquer um invalida
        # o cache, e identidades distintas nunca compartilham token.
        material = '\x1f'.join(
            [
                self._token_url,
                self._client_id,
                self._client_secret,
                self._certificado,
                escopo,
            ]
        )
        return 'sicredi:token:' + hashlib.sha256(material.encode()).hexdigest()

    def token(self, escopo: str) -> str:
        """Devolve um access token válido para o escopo, renovando se preciso."""
        chave = self._chave(escopo)
        token = self._store.get(chave)
        if token is not None and token.valido(self._relogio()):
            return token.access_token
        with self._lock:
            token = self._store.get(chave)
            if token is not None and token.valido(self._relogio()):
                return token.access_token
            token = self._solicitar(escopo)
            ttl = max(int(token.expira_em - self._relogio()), 1)
            self._store.set(chave, token, ttl)
            return token.access_token

    def invalidar(self, escopo: str, access_token: str | None = None) -> None:
        """Descarta o token em cache (ex.: após um 401 da API).

        Com ``access_token``, só descarta se o cache ainda guardar esse mesmo
        token: com 401 concorrentes, a segunda chamada não apaga o token que
        a primeira acabou de renovar.
        """
        chave = self._chave(escopo)
        with self._lock:
            if access_token is not None:
                atual = self._store.get(chave)
                if atual is None or atual.access_token != access_token:
                    return
            self._store.delete(chave)

    def _solicitar(self, escopo: str) -> Token:
        corpo = self._transporte.post_form(
            self._token_url,
            {
                'grant_type': 'client_credentials',
                'client_id': self._client_id,
                'client_secret': self._client_secret,
                'scope': escopo,
            },
            contexto='obter token',
        )
        if not isinstance(corpo, dict) or not corpo.get('access_token'):
            raise RespostaInvalidaError(
                'Resposta do servidor de token sem access_token.', body=corpo
            )
        try:
            validade = int(corpo.get('expires_in') or VALIDADE_PADRAO)
        except (TypeError, ValueError):
            validade = VALIDADE_PADRAO
        return Token(
            access_token=str(corpo['access_token']),
            expira_em=self._relogio() + validade,
            token_type=str(corpo.get('token_type') or 'Bearer'),
        )
