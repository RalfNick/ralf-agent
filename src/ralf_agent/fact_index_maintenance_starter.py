"""Generate an editable automatic native Facts index application."""

import inspect
import json
import re

from . import fact_index_generation, fact_index_maintenance_factories, fact_index_maintenance_tools

_CONFIG = {
    "resource_id": "preference-index",
    "namespace": "preferences",
    "scope": {"workspace": "default", "principal": "local-owner"},
    "backend": {"adapter": "sqlite", "config": {"path": ".ralf/facts.sqlite"}},
    "embedding": {"adapter": "hash", "config": {"dimensions": 16}},
    "index": {
        "adapter": "sqlite",
        "config": {"path": ".ralf/fact-vectors.sqlite", "dimensions": 16},
    },
    "catalog": {
        "adapter": "memory-cas",
        "config": {
            "backend": {"adapter": "sqlite", "config": {"path": ".ralf/fact-catalog.sqlite"}}
        },
    },
    "batch_size": 32,
    "max_pages": 64,
}

_RUNTIME = '''"""Offline observed-preference wiring; edit this provider and rule admission."""
import asyncio
import json
import sqlite3
from pathlib import Path

from ralf_agent import (AgentHarness, AgentSpec, ComponentRegistry, ModelResponse,
    ProfiledEngine, Runtime, RuntimeBuilder, RuntimeProfile, Scope, SQLiteMemory,
    load_catalog)
from ralf_agent.runtime_router import SQLiteRunReader
from ralf_agent.session_types import SessionRef
from ralf_agent.storage import SQLiteStore
from .adapter import (create_fact_index_maintenance_owner, fact_index_maintenance_components,
    maintained_agent_workflow, register_fact_index_maintenance, fact_index_maintenance_writer)

CONFIG = __CONFIG__
SCOPE = Scope(**CONFIG['scope'])


class OfflinePreferenceProvider:
    identity = {'kind':'offline-preference-wiring','version':'1'}

    async def complete(self,messages,tools):
        # Only the actual supplied original context is observed. This fixture
        # demonstrates wiring/lifecycle; it does not assess semantic/model quality.
        task=json.loads(messages[1]['content'])
        observed=[]
        for message in messages:
            content=message.get('content')
            if isinstance(content,str) and content.startswith('Reference memory;'):
                for item in json.loads(content.partition('\\n')[2]):
                    if '_fact_index' in item:
                        value=item['value']
                        observed.append({'key':item['key'],'version':item['version'],
                                         'value':value.get('value') if isinstance(value,dict) else value})
        preference=task.get('preference') if isinstance(task,dict) else None
        if preference is None and observed:preference=observed[-1]['value']
        return ModelResponse(output={'preference':preference or 'green tea',
            'observed_facts':observed,'offline_signal':'wiring-only'},
            usage={'input_tokens':0,'output_tokens':0})


def declarations(borrowed=False):
    values=fact_index_maintenance_components(CONFIG,borrowed=borrowed,prefix='app-')
    values.update(session_store={'adapter':'sqlite'},recall_policy={'adapter':'bounded-recall','config':{
        'facts':{'text':'preference','max_items':8,'max_chars':16000,'scan_limit':32},
        'session':{'max_items':8,'max_chars':16000,'scan_limit':32},'max_pages':1}},
        stage_policy={'adapter':'sourced-memory-async','config':{
            'fields':{'preference':['result','preference']},'namespace':CONFIG['namespace'],
            'memory':fact_index_maintenance_writer(CONFIG,borrowed=borrowed,prefix='app-')}})
    return values


def sdk_profile(borrowed=False):
    return RuntimeProfile('maintained-preferences'+('-borrowed' if borrowed else ''),'1',
        {'default':{'adapter':'offline-preferences'}},declarations(borrowed))


def components(*,borrowed=None):
    registry=ComponentRegistry()
    register_fact_index_maintenance(registry,borrowed=borrowed,prefix='app-')
    registry.register('provider','offline-preferences',lambda config,context:OfflinePreferenceProvider(),
        validator=lambda config: None if not config else (_ for _ in ()).throw(ValueError('Provider fixture takes no config')))
    return registry


def definition():
    reader=AgentSpec(CONFIG['namespace'],'Report observed preferences from the actual supplied Facts evidence',
        output_schema={'type':'object','properties':{'preference':{'type':'string'},
            'observed_facts':{'type':'array'},'offline_signal':{'const':'wiring-only'}},
            'required':['preference','observed_facts','offline_signal'],'additionalProperties':False})
    return maintained_agent_workflow(reader,CONFIG)


def create_engine(db_path):
    # Original read-only ProfiledEngine does not allocate/seed/refresh Facts.
    # Its synchronous dispatch port refuses async factories; use async resume below.
    return ProfiledEngine(load_catalog('runtime.toml'),db_path,
        builder=RuntimeBuilder(components(),base_dir=Path.cwd()),scope=SCOPE)


def seed(preference='coffee'):
    # Explicit host seed only. Run, construction and recovery never call this.
    memory=SQLiteMemory(Path(CONFIG['backend']['config']['path']).resolve())
    try:
        value={'key':'preference','value':preference,'source':{'kind':'explicit-host-seed'}}
        current=memory.inspect_fact(SCOPE,CONFIG['namespace'],'explicit-preference')
        if current is not None and current['value']==value:return {'seeded':0,'version':current['version']}
        version=memory.put_fact(SCOPE,CONFIG['namespace'],'explicit-preference',value,
            expected_version=0 if current is None else current['version'])
        return {'seeded':1,'version':version}
    finally:memory.close()


class ApplicationCleanup:
    def __init__(self):self.runtime=self.instance=self.borrowed_owner=None

    def retain(self,error):
        error.application_cleanup=self
        error.add_note('Retry original application_cleanup.aclose on its original loop after actual drain')

    async def aclose(self,*,close_timeout=None):
        try:
            if self.runtime is not None:await self.runtime.aclose(close_timeout=close_timeout)
            elif self.instance is not None:await self.instance.aclose()
            if self.borrowed_owner is not None:await self.borrowed_owner.aclose()
        except BaseException as error:
            self.retain(error);raise


async def _build(format,borrowed,cleanup,profile=None):
    if borrowed:
        cleanup.borrowed_owner=await create_fact_index_maintenance_owner(CONFIG,base_dir=Path.cwd(),scope=SCOPE)
    if profile is None:
        if format=='sdk':profile=sdk_profile(borrowed)
        else:
            catalog=load_catalog('runtime.'+format)
            catalog.set_default('maintained-preferences'+('-borrowed' if borrowed else ''),'1')
            profile=catalog.default
    cleanup.instance=await RuntimeBuilder(components(borrowed=cleanup.borrowed_owner),base_dir=Path.cwd()).abuild(
        profile,'.ralf/runs.sqlite',scope=SCOPE)
    cleanup.runtime=Runtime(cleanup.instance,owned=True)
    return cleanup.runtime,cleanup.instance


def _connections_closed(native):
    count=0
    for port in native:
        try:port.store.conn.execute('SELECT 1')
        except sqlite3.ProgrammingError:count+=1
    return count


async def run_turns(*,format='toml',borrowed=False,session_id='preferences-session',command_prefix='preferences'):
    cleanup=ApplicationCleanup()
    try:
        runtime,instance=await _build(format,borrowed,cleanup)
        index=instance.memory
        source=cleanup.borrowed_owner.source if borrowed else instance._context._resources[-1].resource
        native=[index.backend,index.index,index.original_catalog.backend]
        records,stages,budgets=[],[],[]
        async with runtime:
            session=await runtime.open_session(AgentHarness(definition()),session_id,command_id=command_prefix+'-open')
            for number,task in enumerate([{'preference':'green tea'},{'task':'What preference do you remember?'}],1):
                run=await session.submit(task,command_id=command_prefix+'-'+str(number),budget=20)
                done=await run.wait(wait_timeout=10,terminal_only=True)
                records.append(instance.store.run(run.ref.run_id))
                stages.append(instance.memory_stages(run.ref.run_id))
                budgets.append(instance.store.budget(run.ref.run_id))
            await session.aclose()
        await cleanup.aclose()
        return {'states':[record['state'] for record in records],'records':records,'memory_stages':stages,
            'budgets':budgets,'profile':instance._engine.runtime_profile,'execution_authority':'local',
            'model_quality':None,'semantic_quality':None,
            'index_module':type(index).__module__,'source_module':type(source).__module__,
            'closure':{'source_closed':source._closed,'native_connections_closed':_connections_closed(native),
                'runtime_resources':len(instance._context._resources),
                'active_handlers':source._owner._execution.active_count,
                'active_tasks':len(asyncio.all_tasks())-1}}
    except BaseException as error:
        cleanup.retain(error);raise
    finally:
        if cleanup.runtime is None or cleanup.runtime.state=='closed':await cleanup.aclose()


async def resume(run_id,*,format='toml',borrowed=False):
    # Rebuild the exact recorded profile; never substitute a new default or seed.
    catalog=load_catalog('runtime.'+('toml' if format=='sdk' else format))
    identity=SQLiteRunReader('.ralf/runs.sqlite',scope=SCOPE).profile_identity(run_id)
    original=catalog.resolve(identity)
    with SQLiteStore('.ralf/runs.sqlite',readonly=True) as reader:
        saved=reader.run(run_id)
    session_ref=SessionRef.from_dict(saved['session_turn']['session']) if 'session_turn' in saved else None
    cleanup=ApplicationCleanup()
    try:
        runtime,instance=await _build(format,borrowed,cleanup,profile=original)
        async with runtime:
            session=runtime.attach_session(session_ref) if session_ref is not None else None
            run=runtime.attach(runtime.reference(run_id))
            await run.resume()
            done=await run.wait(wait_timeout=10,terminal_only=True)
            result={'run_id':run_id,'state':done.snapshot.state,'result':done.snapshot.result,
                'profile':original.identity,'session_ref':session_ref.to_dict() if session_ref is not None else None}
            if session is not None:await session.aclose()
        await cleanup.aclose()
        return result
    except BaseException as error:
        cleanup.retain(error);raise
    finally:
        if cleanup.runtime is None or cleanup.runtime.state=='closed':await cleanup.aclose()
'''

_MAIN = """import argparse
import asyncio
import json
from .runtime import create_engine, resume, run_turns, seed


def main():
    parser=argparse.ArgumentParser(description='Offline automatic index wiring application')
    commands=parser.add_subparsers(dest='operation',required=True)
    seed_command=commands.add_parser('seed');seed_command.add_argument('--preference',default='coffee')
    run=commands.add_parser('run');run.add_argument('--format',choices=('sdk','json','toml'),default='toml')
    run.add_argument('--borrowed',action='store_true');run.add_argument('--command-prefix',required=True)
    run.add_argument('--session-id',default='preferences-session')
    restore=commands.add_parser('resume');restore.add_argument('run_id')
    restore.add_argument('--format',choices=('sdk','json','toml'),default='toml');restore.add_argument('--borrowed',action='store_true')
    observe=commands.add_parser('inspect');observe.add_argument('run_id')
    args=parser.parse_args()
    if args.operation=='seed':result=seed(args.preference)
    elif args.operation=='run':
        result=asyncio.run(run_turns(format=args.format,borrowed=args.borrowed,session_id=args.session_id,command_prefix=args.command_prefix))
    elif args.operation=='resume':result=asyncio.run(resume(args.run_id,format=args.format,borrowed=args.borrowed))
    else:
        engine=create_engine('.ralf/runs.sqlite')
        try:
            from dataclasses import asdict
            result=asdict(engine.diagnostics(args.run_id))
        finally:engine.close()
    print(json.dumps(result,ensure_ascii=False,allow_nan=False))
    return 0


raise SystemExit(main())
"""

_README = """# Automatic native Facts index wiring

Install the locally built wheel and create this application:

```sh
python -m pip install /path/to/ralf_agent-0.1.0.dev98-py3-none-any.whl
ralf init application --template memory-index
cd application
python -m agent_app run --format toml --command-prefix first
```
SDK, JSON and TOML declare the same profile and native SQLite/Hash resource
within one ownership mode. Format changes keep the original default Session.
Changing ownership mode changes its fixed binding: choose a different Session,
e.g. `python -m agent_app run --format json --borrowed --session-id borrowed-preferences --command-prefix second`.
The CLI default remains `preferences-session`; an explicit ID never weakens binding checks.
Each Session turn is a serial Graph: an actual idempotent maintenance ToolAction
with empty caller input must return `ready`, then one preferences reader Agent runs.
The fresh first index has no Facts. The first adopted fixture result commits a
grounded rule-memory preference; the next turn refreshes automatically and its
original model request receives the actual current Fact key/version/value.
No manual rebuild or implicit seed occurs. Session data uses the separate
execution SQLite database; Facts, vectors and catalog each have their own files.

This offline provider is a disclosed wiring signal. Model/semantic quality and
real model services, Team/DAG/Temporal compositions remain unverified.
Existing component registrations and defaults are unchanged by this opt-in helper.

`python -m agent_app seed --preference coffee` explicitly adds/updates a host Fact
and is idempotent for the same value. It never runs during construction or recovery.
`python -m agent_app inspect RUN_ID` uses the original read-only ProfiledEngine;
`python -m agent_app resume RUN_ID` explicitly abuilds the exact recorded profile.
The existing synchronous `ralf --factory agent_app.runtime:create_engine resume`
cannot construct async tools and refuses before native maintenance allocation.

Edit agent_app/runtime.py for your provider/admission fields and agent_app/adapter.py
for native factory options. The paired helper serializes matching resource ID,
trusted Scope, namespace and config; no opaque config digest is user input. Agent
name must match the fixed Facts namespace. Automatic maintenance uses approval=false
as an explicit host grant, exact original effect-key injection and source reconciler.
`partial`/`source_changed` stop the reader. Historical tool receipts never refresh
under the same original Action/key; use a new turn/Action for a new source generation.
No allowance across many Actions is claimed by per-dispatch page/record bounds.

`--borrowed` keeps original native resources in a separate explicit caller owner.
Runtime cleanup owns only its actual Run tasks. ApplicationCleanup retains original
Runtime/RuntimeInstance/borrowed owner on errors; retry aclose on that original loop.
Incomplete source drain/cancellation keeps all borrowed connections live. Native
connections close only after actual source task/thread drain succeeds. Failures
remain reported and the original owner remains available for retry.
"""


def _declaration(borrowed=False):
    components = fact_index_maintenance_factories.fact_index_maintenance_components(
        _CONFIG, borrowed=borrowed, prefix="app-"
    )
    components.update(
        session_store={"adapter": "sqlite"},
        recall_policy={
            "adapter": "bounded-recall",
            "config": {
                "facts": {
                    "text": "preference",
                    "max_items": 8,
                    "max_chars": 16000,
                    "scan_limit": 32,
                },
                "session": {"max_items": 8, "max_chars": 16000, "scan_limit": 32},
                "max_pages": 1,
            },
        },
        stage_policy={
            "adapter": "sourced-memory-async",
            "config": {
                "fields": {"preference": ["result", "preference"]},
                "namespace": _CONFIG["namespace"],
                "memory": fact_index_maintenance_factories.fact_index_maintenance_writer(
                    _CONFIG, borrowed=borrowed, prefix="app-"
                ),
            },
        },
    )
    return {
        "name": "maintained-preferences" + ("-borrowed" if borrowed else ""),
        "version": "1",
        "providers": {"default": {"adapter": "offline-preferences"}},
        "components": components,
    }


def _toml(value):
    if isinstance(value, dict):
        return "{" + ", ".join(json.dumps(k) + " = " + _toml(v) for k, v in value.items()) + "}"
    if isinstance(value, list):
        return "[" + ", ".join(_toml(v) for v in value) + "]"
    return json.dumps(value)


def fact_index_maintenance_files():
    def application_source(module):
        source = inspect.getsource(module)
        return re.sub(
            r"from \.([A-Za-z_][A-Za-z_0-9]*) import",
            lambda match: (
                match.group(0)
                if match.group(1) in {"fact_index_generation", "fact_index_maintenance_tools"}
                else "from ralf_agent." + match.group(1) + " import"
            ),
            source,
        )

    factory = application_source(fact_index_maintenance_factories)
    factory = factory.replace(
        "from fact_index_generation import", "from .fact_index_generation import"
    )
    factory = factory.replace(
        "from fact_index_maintenance_tools import", "from .fact_index_maintenance_tools import"
    )
    tools = application_source(fact_index_maintenance_tools).replace(
        "from fact_index_generation import", "from .fact_index_generation import"
    )
    declaration = {
        "schema_version": 1,
        "default": {"name": "maintained-preferences", "version": "1"},
        "profiles": [_declaration(), _declaration(True)],
    }
    return {
        "agent_app/__init__.py": "",
        "agent_app/adapter.py": factory,
        "agent_app/fact_index_generation.py": application_source(fact_index_generation),
        "agent_app/fact_index_maintenance_tools.py": tools,
        "agent_app/runtime.py": _RUNTIME.replace("__CONFIG__", repr(_CONFIG)),
        "agent_app/__main__.py": _MAIN,
        "runtime.json": json.dumps(declaration, indent=2) + "\n",
        "runtime.toml": "\n".join(key + " = " + _toml(value) for key, value in declaration.items())
        + "\n",
        ".gitignore": ".ralf/\n__pycache__/\n",
        "README.md": _README,
    }
