"""Bounded native/HTTP process boundary; parent alone owns durable authority.

The child sends reserve BEFORE the common transport can transmit, and receives
its committed ticket by pipe. It never gets database credentials. A child release
message is merely a proposal: parent verifies process exit before releasing DB
ownership. This drains native decoder threads even on timeout/cancellation.
"""
import asyncio
import json
import os
from pathlib import Path
import signal
import sys
import time
from worker.jobs.sampling_study_store import StudyFence,StudyPause

async def _stop_and_wait(proc):
    if proc.returncode is None:
        try:os.killpg(proc.pid,signal.SIGTERM)
        except ProcessLookupError:pass
        try:await asyncio.wait_for(asyncio.shield(proc.wait()),3)
        except (asyncio.TimeoutError,asyncio.CancelledError):
            try:os.killpg(proc.pid,signal.SIGKILL)
            except ProcessLookupError:pass
    # Do not report drain or release authority before actual process exit.
    while proc.returncode is None:
        try:await asyncio.shield(proc.wait())
        except asyncio.CancelledError:continue
    return True

async def run_supervised(store,input_dir,*,seconds=3300,command=None):
    if not 1<=seconds<=3300 or store.manifest is None:raise StudyFence('study_process_setup')
    root=Path(input_dir).resolve()
    if not root.is_dir():raise StudyFence('study_input_directory')
    # command injection is test-only dependency injection, never a CLI input.
    cmd=command or [sys.executable,'-m','worker.jobs.sampling_study_process','--child']
    env={k:os.environ[k] for k in ('PATH','LANG','LC_ALL','SYSTEMROOT') if k in os.environ}
    env.update(HOME='/tmp',PYTHONDONTWRITEBYTECODE='1',PYTHON_DOTENV_DISABLED='1',CONCURRENT_RECOGNITIONS='1',QUOTA_COOLDOWN_DURATION='60')
    proc=await asyncio.create_subprocess_exec(*cmd,stdin=asyncio.subprocess.PIPE,stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,start_new_session=True,env=env,limit=262144)
    deadline=time.monotonic()+seconds+15;proposal=None;error=None
    async def answer(value):
        proc.stdin.write((json.dumps(value,separators=(',',':'))+'\n').encode())
        await asyncio.wait_for(proc.stdin.drain(),min(10,max(.001,deadline-time.monotonic())))
    try:
        await answer({'manifest':store.manifest,'input_dir':str(root),'seconds':seconds})
        while True:
            remaining=deadline-time.monotonic()
            if remaining<=0:raise StudyPause('study_process_deadline')
            line=await asyncio.wait_for(proc.stdout.readline(),remaining)
            if not line:break
            if len(line)>262144:raise StudyFence('study_ipc_limit')
            q=json.loads(line)
            if not isinstance(q,dict) or set(q)!={'op','args'} or not isinstance(q['args'],list):raise StudyFence('study_ipc_shape')
            op,args=q['op'],q['args']
            if op=='completed' and not args:out=sorted(store.completed_ids())
            elif op=='reserve' and len(args)==2:out=store.reserve(*args)
            elif op=='finish' and len(args)==3:out=store.finish(*args).delay_seconds
            elif op=='release' and len(args)==1 and args[0] in ('complete','paused','cancelled','error'):
                if proposal is not None:raise StudyFence('study_duplicate_release')
                proposal=args[0];out=True
            else:raise StudyFence('study_ipc_operation')
            if proposal is not None and op!='release':raise StudyFence('study_work_after_release')
            await answer({'ok':out})
        await asyncio.wait_for(proc.wait(),max(.001,deadline-time.monotonic()))
        if proc.returncode!=0 or proposal is None:raise StudyFence('study_child_failed')
    except BaseException as exc:
        error=exc
    finally:
        drained=await _stop_and_wait(proc)
        if proc.stdin is not None:proc.stdin.close()
        # An uncertain reservation remains charged and status becomes uncertain.
        # Database failure here is not concealed as a successful release.
        status=store.release(proposal if error is None else 'error',transport_drained=drained)
    if error is not None:raise error
    return status

class ChildStore:
    def __init__(self,manifest):
        from worker.jobs.sampling_study_manifest import validate
        self.manifest=manifest;self.windows=validate(manifest)
    def rpc(self,op,args):
        sys.stdout.write(json.dumps({'op':op,'args':args},separators=(',',':'))+'\n');sys.stdout.flush()
        line=sys.stdin.readline(262145)
        if not line or len(line)>262144:raise StudyFence('study_parent_unavailable')
        result=json.loads(line)
        if set(result)!={'ok'}:raise StudyFence('study_parent_refused')
        return result['ok']
    def completed_ids(self):return set(self.rpc('completed',[]))
    def reserve(self,*args):return self.rpc('reserve',list(args))
    def finish(self,*args):
        from recognition_retry_policy import RetryDirective
        return RetryDirective(self.rpc('finish',list(args)))
    def release(self,reason,*,transport_drained):
        # This is only a proposal; the parent waits for this process to exit.
        return self.rpc('release',[reason])

async def child():
    import resource
    resource.setrlimit(resource.RLIMIT_CPU,(300,300));resource.setrlimit(resource.RLIMIT_CORE,(0,0))
    resource.setrlimit(resource.RLIMIT_AS,(1024*1024*1024,1024*1024*1024))
    resource.setrlimit(resource.RLIMIT_FSIZE,(16*1024*1024,16*1024*1024))
    resource.setrlimit(resource.RLIMIT_NOFILE,(64,64))
    line=sys.stdin.readline(131073)
    if not line or len(line)>131072:raise StudyFence('study_initial_message')
    p=json.loads(line)
    if set(p)!={'manifest','input_dir','seconds'}:raise StudyFence('study_initial_shape')
    root=Path(p['input_dir']).resolve();store=ChildStore(p['manifest'])
    def load(w):
        path=root/(w['id']+'.wav')
        if path.is_symlink():raise StudyFence('study_input_symlink')
        with path.open('rb') as f:return f.read(1000001)
    from worker.jobs.sampling_study import run_prepared
    await run_prepared(store,load,seconds=p['seconds'])

def main():
    if sys.argv[1:]!=['--child']:raise SystemExit('No live study CLI. Child entry is supervised over private pipes only.')
    try:asyncio.run(child())
    except BaseException:raise SystemExit(1) from None

if __name__=='__main__':main()
