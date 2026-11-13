from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
import responses
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import pkcs12
from cryptography.x509.oid import NameOID

from sicredi import Sicredi

SANDBOX = 'https://mtls-api-parceiro.sicredi.com.br/sb'
PRODUCAO = 'https://mtls-api-parceiro.sicredi.com.br'
TOKEN_SB = f'{SANDBOX}/thirdparty/auth/token'
EXTRATO_SB = f'{SANDBOX}/contacorrente/v1/extratos'
SALDO_SB = f'{SANDBOX}/contacorrente/v1/saldos'


def gerar_certificado(dias: int = 365):
    chave = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    nome = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'teste-sicredi')])
    agora = datetime.now(timezone.utc)
    inicio = agora - timedelta(days=2 + max(0, -dias))
    cert = (
        x509.CertificateBuilder()
        .subject_name(nome)
        .issuer_name(nome)
        .public_key(chave.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(inicio)
        .not_valid_after(agora + timedelta(days=dias))
        .sign(chave, hashes.SHA256())
    )
    return chave, cert


@pytest.fixture(scope='session')
def par():
    return gerar_certificado()


@pytest.fixture(scope='session')
def pem_cert(par) -> bytes:
    return par[1].public_bytes(serialization.Encoding.PEM)


@pytest.fixture(scope='session')
def pem_chave(par) -> bytes:
    return par[0].private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )


@pytest.fixture(scope='session')
def pfx(par) -> bytes:
    return pkcs12.serialize_key_and_certificates(
        b'teste',
        par[0],
        par[1],
        None,
        serialization.BestAvailableEncryption(b'senha-pfx'),
    )


@pytest.fixture
def mock_http():
    with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        yield rsps


def registrar_token(rsps, token: str = 'tok-1', expires_in: int = 3600, url=TOKEN_SB):
    return rsps.add(
        responses.POST,
        url,
        json={'access_token': token, 'token_type': 'Bearer', 'expires_in': expires_in},
    )


@pytest.fixture
def cliente(pfx):
    with Sicredi(
        'client-id',
        'client-secret',
        ambiente='sandbox',
        certificado_pfx=pfx,
        senha_pfx='senha-pfx',
    ) as sicredi:
        yield sicredi
