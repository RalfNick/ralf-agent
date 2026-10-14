"""Structural native peer with account RAM only; never persists login params."""

from tests.test_codex_connected_profile import native_results
from tests.test_codex_runner import native_fixture


def connected_native_fixture(tmp_path, connection, mode="completed"):
    cli = native_fixture(tmp_path, "hang_turn" if mode == "hang_turn" else "completed")
    source = cli.read_text()
    start = source.index(" control=")
    end = source.index(";thread_response=", start)
    source = source[:start] + f" control={native_results(connection)!r}" + source[end:]
    branch = """
  if method in ['account/read','account/login/start']:
   with (root/'auth-methods.txt').open('a') as out:out.write(method+'\\n')
  if method=='account/read':
   result={'account':{'type':'apiKey'} if globals().get('authed',False) else None,'requiresOpenaiAuth':True}
  elif method=='account/login/start':
   authed=True
   if AUTH_MODE=='hang_login':time.sleep(10)
   result={'type':'apiKey'}
   if AUTH_MODE=='echo':result['extra']=message['params']['apiKey']
   send({'id':message['id'],'result':result})
   send({'method':'account/login/completed','params':{'loginId':None,'success':True,'error':None}})
   send({'method':'account/updated','params':{'authMode':'apikey','planType':None}})
   continue
  elif method in control:result=control[method]
""".replace("AUTH_MODE", repr(mode))
    source = source.replace("  if method in control:result=control[method]", branch.rstrip())
    cli.write_text(source)
    return cli
