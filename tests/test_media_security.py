from __future__ import annotations
import io
from dataclasses import replace
import socket
import time
from unittest.mock import patch

from PIL import Image
import pytest

from augurama.errors import DirectorError
from augurama.safe_fetch import public_destination,SafeFetcher
from conftest import FIXTURES

@pytest.mark.parametrize('url',[
 'http://example.com/a','https://127.0.0.1/a','https://169.254.169.254/latest/meta-data',
 'https://[::1]/a','https://[fd00::1]/a','https://10.0.0.1/a','https://example.com:444/a',
 'https://user:pass@example.com/a','https://localhost/a','file:///etc/passwd',
 'https://example.com./a','https://example.com/a#x','https://example.com/\\evil',
 'https://example.com/a\nfoo','https://metadata.google.internal/a'])
def test_private_or_unsafe_media_urls_rejected(url):
    # DNS is controlled, not actually sent to the network.
    def resolver(host,port,**kwargs):
        address=host if host in ('127.0.0.1','169.254.169.254','::1','fd00::1','10.0.0.1') else '8.8.8.8'
        return [(socket.AF_INET,socket.SOCK_STREAM,6,'',(address,port))]
    with patch('socket.getaddrinfo',resolver),pytest.raises(DirectorError,match='public HTTPS'):public_destination(url)


def test_dns_mixed_private_and_public_is_rejected_and_pinned_public_accepted():
    records=[(socket.AF_INET,socket.SOCK_STREAM,6,'',('8.8.8.8',443)),(socket.AF_INET,socket.SOCK_STREAM,6,'',('127.0.0.1',443))]
    with patch('socket.getaddrinfo',return_value=records),pytest.raises(DirectorError):public_destination('https://files.example/a')
    with patch('socket.getaddrinfo',return_value=records[:1]):assert public_destination('https://files.example/a?token=private')==('files.example','8.8.8.8','/a?token=private')

class Response:
    def __init__(self,status=200,headers=None,body=b'file'):self.status=status;self.headers=headers or {};self.body=io.BytesIO(body)
    def getheader(self,name,default=None):return self.headers.get(name,default)
    def read(self,n):return self.body.read(n)
class Connection:
    response=Response()
    def __init__(self,host,ip):self.host=host;self.ip=ip
    def request(self,method,path,headers):assert method=='GET' and 'Authorization' not in headers
    def getresponse(self):return self.response
    def close(self):pass

@pytest.mark.parametrize('response,code',[
    (Response(headers={'Content-Length':'500'}),'MEDIA_TOO_LARGE'),
    (Response(body=b'123456789'),'MEDIA_TOO_LARGE'),
    (Response(headers={'Content-Encoding':'gzip'}),'MEDIA_ENCODING_REJECTED'),
    (Response(status=404),'MEDIA_DOWNLOAD_FAILED'),
    (Response(status=302),'MEDIA_DOWNLOAD_FAILED')])
def test_fetcher_bounds_redirects_and_encoded_content(response,code):
    with patch('augurama.safe_fetch.public_destination',return_value=('files.example','8.8.8.8','/a')),patch('augurama.safe_fetch.PinnedHTTPS',Connection):
        Connection.response=response
        with pytest.raises(DirectorError) as exc:SafeFetcher().download('https://files.example/a',5)
        assert exc.value.code==code


def test_redirect_target_is_revalidated():
    Connection.response=Response(status=302,headers={'Location':'https://127.0.0.1/a'})
    with patch('augurama.safe_fetch.public_destination',side_effect=[('files.example','8.8.8.8','/a'),DirectorError('UNSAFE_MEDIA_URL','blocked')]) as destination,patch('augurama.safe_fetch.PinnedHTTPS',Connection),pytest.raises(DirectorError,match='blocked'):
        SafeFetcher().download('https://files.example/a',100)
    assert destination.call_args_list[-1].args[0]=='https://127.0.0.1/a'


def test_input_validation_quota_and_signed_media_expiration(engine,uid):
    with pytest.raises(DirectorError):engine.assets.inspect(b'not an image or video')
    tiny=io.BytesIO();Image.new('RGB',(100,100)).save(tiny,format='PNG')
    with pytest.raises(DirectorError,match='300'):engine.assets.inspect(tiny.getvalue())
    asset=engine.assets.ingest(uid,(FIXTURES/'provider-test-frame.png').read_bytes(),'../moon\x00.png','synthetic')
    assert '/' not in asset['name'] and '\x00' not in asset['name']
    engine.assets.settings=replace(engine.settings,max_account_bytes=1)
    with pytest.raises(DirectorError,match='quota'):engine.assets.ingest(uid,(FIXTURES/'provider-test-frame.png').read_bytes(),'copy.png','synthetic')


def test_archival_origin_expiration_is_conservative(engine,uid,approval):
    job=engine.submit(uid,approval)
    created=time.time()-22*3600
    engine.db.execute('UPDATE jobs SET created_at=? WHERE id=?',(created,job['generation_id']))
    result=engine.get(uid,job['generation_id'])
    asset=engine.assets.get(uid,result['result']['video_asset_id'])
    assert asset['provider_original_expires']<=created+23*3600+1
