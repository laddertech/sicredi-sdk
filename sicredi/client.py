"""Cliente principal do SDK."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sicredi._http import Transporte
from sicredi.auth import OAuth2Client, TokenStore
from sicredi.certificado import (
    FonteBinaria,
    Identidade,
    Senha,
    carregar_pem,
    carregar_pfx,
)
from sicredi.config import Ambiente, Config
from sicredi.conta_corrente import ContaCorrenteAPI
from sicredi.exceptions import CertificadoError, ConfiguracaoError

if TYPE_CHECKING:
    from types import TracebackType


class Sicredi:
    """Cliente das APIs de parceiros do Sicredi.

    Toda a configuração é explícita e por instância: o SDK não lê variáveis
    de ambiente nem guarda estado global. O ambiente é obrigatório para que
    nenhum código chegue à produção por omissão.

    Informe o certificado mTLS **ou** como PFX (``certificado_pfx`` +
    ``senha_pfx``) **ou** como par PEM (``certificado`` + ``chave_privada``,
    com ``senha_chave`` se a chave for protegida).

    Exemplo::

        from datetime import date
        from sicredi import Sicredi

        with Sicredi(
            client_id='...',
            client_secret='...',
            certificado_pfx='certificado.pfx',
            senha_pfx='...',
            ambiente='sandbox',
        ) as sicredi:
            extrato = sicredi.conta_corrente.extrato(
                date(2026, 11, 1), date(2026, 11, 13)
            )
            saldo = sicredi.conta_corrente.saldo()

    Args:
        client_id: Client ID gerado no Portal do Desenvolvedor.
        client_secret: Client Secret correspondente.
        ambiente: ``"sandbox"`` ou ``"producao"`` (ou :class:`Ambiente`).
        certificado_pfx: caminho, bytes ou arquivo aberto do PFX/P12.
        senha_pfx: senha do PFX.
        certificado: caminho, bytes ou texto PEM do certificado.
        chave_privada: caminho, bytes ou texto PEM da chave privada.
        senha_chave: senha da chave PEM, se houver.
        base_url: raiz explícita da API (sobrepõe a do ambiente).
        timeout: timeout de cada requisição, em segundos.
        token_store: cache de tokens; padrão em memória do processo.

    Raises:
        ConfiguracaoError: credencial ausente ou ambiente inválido.
        CertificadoError: certificado ausente, ilegível, com senha errada ou
            vencido.
    """

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        *,
        ambiente: Ambiente | str,
        certificado_pfx: FonteBinaria | None = None,
        senha_pfx: Senha = None,
        certificado: FonteBinaria | None = None,
        chave_privada: FonteBinaria | None = None,
        senha_chave: Senha = None,
        base_url: str | None = None,
        timeout: float = 30.0,
        token_store: TokenStore | None = None,
    ) -> None:
        if not client_id or not str(client_id).strip():
            raise ConfiguracaoError('client_id é obrigatório.')
        if not client_secret or not str(client_secret).strip():
            raise ConfiguracaoError('client_secret é obrigatório.')
        if timeout <= 0:
            raise ConfiguracaoError('timeout deve ser positivo.')

        self.config = Config(
            ambiente=Ambiente.parse(ambiente), base_url=base_url, timeout=timeout
        )
        self.identidade = self._carregar_identidade(
            certificado_pfx, senha_pfx, certificado, chave_privada, senha_chave
        )
        self._transporte = Transporte(self.identidade, timeout, self.config.origem)
        self._oauth = OAuth2Client(
            self._transporte,
            client_id=str(client_id).strip(),
            client_secret=str(client_secret).strip(),
            token_url=self.config.token_url,
            token_store=token_store,
            certificado_fingerprint=self.identidade.fingerprint,
        )
        self.conta_corrente = ContaCorrenteAPI(
            self._transporte, self._oauth, self.config
        )

    @staticmethod
    def _carregar_identidade(
        certificado_pfx: FonteBinaria | None,
        senha_pfx: Senha,
        certificado: FonteBinaria | None,
        chave_privada: FonteBinaria | None,
        senha_chave: Senha,
    ) -> Identidade:
        usa_pfx = certificado_pfx is not None
        usa_pem = certificado is not None or chave_privada is not None
        if usa_pfx and usa_pem:
            raise CertificadoError(
                'Informe o certificado como PFX ou como par PEM, não ambos.'
            )
        if usa_pfx:
            identidade = carregar_pfx(certificado_pfx, senha_pfx)  # type: ignore[arg-type]
        elif certificado is not None and chave_privada is not None:
            identidade = carregar_pem(certificado, chave_privada, senha_chave)
        elif usa_pem:
            raise CertificadoError(
                'O par PEM exige certificado e chave_privada juntos.'
            )
        else:
            raise CertificadoError(
                'Certificado mTLS obrigatório: informe certificado_pfx ou '
                'certificado + chave_privada.'
            )
        if identidade.expirado:
            raise CertificadoError(
                f'Certificado vencido em {identidade.valido_ate:%d/%m/%Y}.'
            )
        return identidade

    @property
    def ambiente(self) -> Ambiente:
        return self.config.ambiente

    def close(self) -> None:
        """Fecha a sessão HTTP."""
        self._transporte.close()

    def __enter__(self) -> Sicredi:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    def __repr__(self) -> str:
        return f'Sicredi(ambiente={self.ambiente.value!r})'
