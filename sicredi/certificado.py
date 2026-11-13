"""Carga do certificado mTLS (PFX/PKCS#12 ou par PEM).

Toda identidade vira um único PKCS#12 em memória, que é o que o
``requests_pkcs12`` monta na sessão. Assim PFX e PEM seguem o mesmo caminho
e o certificado é validado **na construção do cliente** — senha errada ou
arquivo trocado falham cedo, com :class:`CertificadoError`, e não na primeira
chamada à API.
"""

from __future__ import annotations

import os
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import BinaryIO, Union

from cryptography import x509
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.serialization import (
    BestAvailableEncryption,
    Encoding,
    PublicFormat,
    load_pem_private_key,
    pkcs12,
)

from sicredi.exceptions import CertificadoError

FonteBinaria = Union[str, bytes, os.PathLike, BinaryIO]  # noqa: UP007
Senha = Union[str, bytes, None]  # noqa: UP007


def _ler(fonte: FonteBinaria, nome: str) -> bytes:
    """Lê bytes de um caminho, de bytes já carregados ou de arquivo aberto.

    Uma ``str`` que começa com ``-----BEGIN`` é tratada como conteúdo PEM,
    não como caminho.
    """
    if isinstance(fonte, bytes):
        return fonte
    if isinstance(fonte, str) and fonte.lstrip().startswith('-----BEGIN'):
        return fonte.encode('ascii')
    if isinstance(fonte, (str, os.PathLike)):
        try:
            with open(fonte, 'rb') as arquivo:
                return arquivo.read()
        except OSError as exc:
            raise CertificadoError(f'Não foi possível ler {nome}: {exc}') from exc
    if hasattr(fonte, 'read'):
        dados = fonte.read()
        if isinstance(dados, str):
            dados = dados.encode('ascii')
        return dados
    raise CertificadoError(f'Tipo não suportado para {nome}: {type(fonte).__name__}')


def _senha_bytes(senha: Senha) -> bytes | None:
    if senha is None or senha == '' or senha == b'':
        return None
    if isinstance(senha, str):
        return senha.encode('utf-8')
    return senha


@dataclass(frozen=True)
class Identidade:
    """Certificado + chave prontos para mTLS, serializados em PKCS#12."""

    pkcs12_data: bytes = field(repr=False)
    senha: bytes = field(repr=False)
    titular: str
    fingerprint: str  # SHA-256 do certificado (DER), em hex
    valido_ate: datetime

    @property
    def expirado(self) -> bool:
        return self.valido_ate <= datetime.now(timezone.utc)


def _identidade(chave, certificado: x509.Certificate, adicionais) -> Identidade:
    if chave.public_key().public_bytes(
        Encoding.DER, PublicFormat.SubjectPublicKeyInfo
    ) != certificado.public_key().public_bytes(
        Encoding.DER, PublicFormat.SubjectPublicKeyInfo
    ):
        raise CertificadoError('A chave privada não corresponde ao certificado.')
    senha = secrets.token_hex(16).encode('ascii')
    try:
        dados = pkcs12.serialize_key_and_certificates(
            name=None,
            key=chave,
            cert=certificado,
            cas=adicionais or None,
            encryption_algorithm=BestAvailableEncryption(senha),
        )
    except (ValueError, TypeError) as exc:
        raise CertificadoError(f'Certificado/chave não suportados: {exc}') from exc
    return Identidade(
        pkcs12_data=dados,
        senha=senha,
        titular=certificado.subject.rfc4514_string(),
        fingerprint=certificado.fingerprint(hashes.SHA256()).hex(),
        valido_ate=certificado.not_valid_after_utc,
    )


def carregar_pfx(certificado_pfx: FonteBinaria, senha_pfx: Senha = None) -> Identidade:
    """Carrega um PFX/P12 (formato em que o ERP guarda os certificados)."""
    dados = _ler(certificado_pfx, 'certificado PFX')
    try:
        chave, certificado, adicionais = pkcs12.load_key_and_certificates(
            dados, _senha_bytes(senha_pfx)
        )
    except ValueError as exc:
        raise CertificadoError('Certificado PFX inválido ou senha incorreta.') from exc
    if chave is None or certificado is None:
        raise CertificadoError('O PFX precisa conter o certificado e a chave privada.')
    return _identidade(chave, certificado, adicionais)


def carregar_pem(
    certificado: FonteBinaria,
    chave_privada: FonteBinaria,
    senha_chave: Senha = None,
) -> Identidade:
    """Carrega o par PEM emitido pelo Portal do Desenvolvedor Sicredi.

    O arquivo de certificado pode trazer a cadeia; o primeiro bloco é o do
    cliente e os seguintes viram certificados adicionais.
    """
    dados_cert = _ler(certificado, 'certificado PEM')
    dados_chave = _ler(chave_privada, 'chave privada PEM')
    try:
        cadeia = x509.load_pem_x509_certificates(dados_cert)
    except ValueError as exc:
        raise CertificadoError('Certificado PEM inválido.') from exc
    try:
        chave = load_pem_private_key(dados_chave, password=_senha_bytes(senha_chave))
    except (ValueError, TypeError) as exc:
        raise CertificadoError(
            'Chave privada PEM inválida, protegida por senha não informada '
            'ou senha incorreta.'
        ) from exc
    return _identidade(chave, cadeia[0], cadeia[1:])
