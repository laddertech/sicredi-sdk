import io

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.serialization import pkcs12

from sicredi import CertificadoError, Sicredi
from sicredi.certificado import carregar_pem, carregar_pfx

from .conftest import gerar_certificado


def _pkcs12_ok(identidade):
    chave, cert, _ = pkcs12.load_key_and_certificates(
        identidade.pkcs12_data, identidade.senha
    )
    assert chave is not None and cert is not None


def test_pfx_bytes(pfx):
    identidade = carregar_pfx(pfx, 'senha-pfx')
    _pkcs12_ok(identidade)
    assert 'teste-sicredi' in identidade.titular
    assert not identidade.expirado


def test_pfx_caminho_e_arquivo_aberto(pfx, tmp_path):
    caminho = tmp_path / 'cert.pfx'
    caminho.write_bytes(pfx)
    _pkcs12_ok(carregar_pfx(str(caminho), b'senha-pfx'))
    _pkcs12_ok(carregar_pfx(caminho, 'senha-pfx'))
    _pkcs12_ok(carregar_pfx(io.BytesIO(pfx), 'senha-pfx'))


def test_pfx_senha_errada(pfx):
    with pytest.raises(CertificadoError, match='senha incorreta'):
        carregar_pfx(pfx, 'errada')


def test_pfx_arquivo_inexistente(tmp_path):
    with pytest.raises(CertificadoError, match='Não foi possível ler'):
        carregar_pfx(str(tmp_path / 'nao-existe.pfx'), 'x')


def test_pfx_sem_chave(par):
    sem_chave = pkcs12.serialize_key_and_certificates(
        None, None, None, [par[1]], serialization.NoEncryption()
    )
    with pytest.raises(CertificadoError, match='chave privada'):
        carregar_pfx(sem_chave)


def test_pem_bytes_texto_e_caminho(pem_cert, pem_chave, tmp_path):
    _pkcs12_ok(carregar_pem(pem_cert, pem_chave))
    _pkcs12_ok(carregar_pem(pem_cert.decode(), pem_chave.decode()))
    (tmp_path / 'c.pem').write_bytes(pem_cert)
    (tmp_path / 'k.pem').write_bytes(pem_chave)
    _pkcs12_ok(carregar_pem(str(tmp_path / 'c.pem'), str(tmp_path / 'k.pem')))


def test_pem_com_cadeia(pem_cert, pem_chave):
    _, outro = gerar_certificado()
    cadeia = pem_cert + outro.public_bytes(serialization.Encoding.PEM)
    identidade = carregar_pem(cadeia, pem_chave)
    _, _, adicionais = pkcs12.load_key_and_certificates(
        identidade.pkcs12_data, identidade.senha
    )
    assert len(adicionais) == 1


def test_pem_chave_protegida(par, pem_cert):
    chave_cifrada = par[0].private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.BestAvailableEncryption(b'frase'),
    )
    _pkcs12_ok(carregar_pem(pem_cert, chave_cifrada, 'frase'))
    with pytest.raises(CertificadoError, match='Chave privada'):
        carregar_pem(pem_cert, chave_cifrada)


def test_pem_invalido(pem_chave):
    with pytest.raises(CertificadoError, match='Certificado PEM inválido'):
        carregar_pem(b'lixo', pem_chave)


def test_identidade_nao_expoe_segredos_no_repr(pfx):
    texto = repr(carregar_pfx(pfx, 'senha-pfx'))
    assert 'pkcs12_data' not in texto
    assert 'senha' not in texto


@pytest.mark.parametrize(
    ('kwargs', 'mensagem'),
    [
        ({}, 'obrigatório'),
        ({'certificado': b'x'}, 'juntos'),
        ({'chave_privada': b'x'}, 'juntos'),
    ],
)
def test_cliente_exige_certificado_coerente(kwargs, mensagem):
    with pytest.raises(CertificadoError, match=mensagem):
        Sicredi('id', 'secret', ambiente='sandbox', **kwargs)


def test_cliente_recusa_pfx_e_pem_juntos(pfx, pem_cert, pem_chave):
    with pytest.raises(CertificadoError, match='não ambos'):
        Sicredi(
            'id',
            'secret',
            ambiente='sandbox',
            certificado_pfx=pfx,
            senha_pfx='senha-pfx',
            certificado=pem_cert,
            chave_privada=pem_chave,
        )


def test_cliente_recusa_certificado_vencido():
    chave, cert = gerar_certificado(dias=-1)
    with pytest.raises(CertificadoError, match='vencido'):
        Sicredi(
            'id',
            'secret',
            ambiente='sandbox',
            certificado=cert.public_bytes(serialization.Encoding.PEM),
            chave_privada=chave.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption(),
            ),
        )


def test_pem_par_trocado(pem_cert):
    outra_chave, _ = gerar_certificado()
    chave_pem = outra_chave.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    with pytest.raises(CertificadoError, match='não corresponde'):
        carregar_pem(pem_cert, chave_pem)
