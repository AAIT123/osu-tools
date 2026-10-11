"""Small, opt-in osu! API v2 client. No external Python dependencies."""
import json
import os
from pathlib import Path
import stat
import time
import urllib.error
import urllib.parse
import urllib.request
from .paths import cache_dir, config_dir

API_BASE = 'https://osu.ppy.sh'


class ApiError(RuntimeError):
    pass


def credentials():
    cid = os.environ.get('OSU_API_CLIENT_ID')
    secret = os.environ.get('OSU_API_CLIENT_SECRET')
    if cid and secret:
        return str(cid), secret
    for filename in (config_dir() / 'api.conf', Path('~/.local/share/osu-tools/api.conf').expanduser()):
        if not filename.is_file():
            continue
        if os.name == 'posix' and filename.stat().st_mode & (stat.S_IRGRP | stat.S_IROTH):
            raise ApiError(f'{filename} is readable by other users; chmod 600 it first')
        vals = {}
        for line in filename.read_text(encoding='utf-8').splitlines():
            k, sep, v = line.strip().partition('=')
            if sep and not k.startswith('#'):
                vals[k.strip()] = v.strip().strip('"\'')
        if vals.get('client_id') and vals.get('client_secret'):
            return vals['client_id'], vals['client_secret']
    raise ApiError('API credentials missing; set OSU_API_CLIENT_ID/OSU_API_CLIENT_SECRET '
                   'or ~/.config/osu-tools/api.conf with client_id= and client_secret= (chmod 600)')


class Client:
    def __init__(self, base=API_BASE, opener=None, token=None):
        self.base = base.rstrip('/')
        self.opener = opener or urllib.request.urlopen
        self._token = token

    def token(self):
        if self._token:
            return self._token
        cid, secret = credentials()
        cache = cache_dir() / 'token.json'
        try:
            blob = json.loads(cache.read_text())
            if blob.get('client_id') == cid and blob.get('expires_at', 0) > time.time() + 60:
                self._token = blob['access_token']
                return self._token
        except (OSError, ValueError, KeyError, TypeError):
            pass
        body = urllib.parse.urlencode({'client_id': cid, 'client_secret': secret,
                                      'grant_type': 'client_credentials', 'scope': 'public'}).encode()
        request = urllib.request.Request(self.base+'/oauth/token', data=body,
                                         headers={'Accept': 'application/json',
                                                  'Content-Type': 'application/x-www-form-urlencoded'})
        data = self._request(request)
        self._token = data['access_token']
        try:
            cache.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            # Write atomically to prevent torn cache records.
            import tempfile
            fd, temp = tempfile.mkstemp(dir=cache.parent, prefix='.token-')
            try:
                os.chmod(temp, 0o600)
                with os.fdopen(fd, 'w', encoding='utf-8') as f:
                    json.dump({'client_id': cid, 'access_token': self._token,
                               'expires_at': time.time()+int(data.get('expires_in', 3600))}, f)
                os.replace(temp, cache)
            finally:
                if os.path.exists(temp):
                    os.unlink(temp)
        except OSError:
            pass  # cache failures must not prevent API calls
        return self._token

    def _request(self, request):
        try:
            with self.opener(request, timeout=15) as resp:
                return json.load(resp)
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return None
            if exc.code == 429:
                raise ApiError('osu! API rate limit reached; retry later') from exc
            raise ApiError(f'osu! API returned HTTP {exc.code} for {request.full_url}') from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            raise ApiError(f'Cannot reach osu! API: {exc}') from exc
        except (ValueError, KeyError) as exc:
            raise ApiError('Unexpected osu! API response') from exc

    def get(self, path, params=None):
        url = self.base + '/api/v2/' + path.lstrip('/')
        if params:
            url += '?' + urllib.parse.urlencode(params)
        request = urllib.request.Request(url, headers={
            'Authorization': 'Bearer ' + self.token(),
            'Accept': 'application/json',
            'User-Agent': 'osu-tools/0.2 (personal lightweight CLI)'})
        try:
            return self._request(request)
        except ApiError as exc:
            if 'HTTP 401 ' in str(exc):
                self._token = None
                request.remove_header('Authorization')
                # revoke cache: token may have been invalidated early
                try: (cache_dir() / 'token.json').unlink()
                except OSError: pass
                request.add_header('Authorization', 'Bearer '+self.token())
                return self._request(request)
            raise

    def user(self, name, mode='osu'):
        return self.get('users/'+urllib.parse.quote(str(name), safe='')+'/'+mode,
                        {'key': 'id' if str(name).isdigit() else 'username'})

    def beatmap_for_checksum(self, checksum):
        return self.get('beatmaps/lookup', {'checksum': checksum})

    def beatmap_scores(self, beatmap_id, mode):
        return self.get(f'beatmaps/{beatmap_id}/scores', {'mode': mode})

    def user_score(self, beatmap_id, user_id, mode):
        return self.get(f'beatmaps/{beatmap_id}/scores/users/{user_id}', {'mode': mode})
