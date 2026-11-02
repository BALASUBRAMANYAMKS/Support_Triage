"""Single provider client with fallback, retry, cache and structured JSON output."""
from __future__ import annotations
import hashlib, json, logging, os, time, uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from threading import RLock
from typing import Any
from dotenv import load_dotenv
import yaml

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / '.env')
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger('support_triage.llm')
_LOCK = RLock()

@dataclass
class LLMResult:
    content: str
    provider: str
    model: str
    prompt_hash: str
    tokens_in: int = 0
    tokens_out: int = 0
    latency_ms: int = 0
    cache_hit: bool = False
    fallback_used: bool = False


def _config():
    with (ROOT / 'config.yaml').open(encoding='utf-8-sig') as f:
        return yaml.safe_load(f)


def _cache_path(config):
    return ROOT / config['app']['cache_path']


def _load_cache(path):
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError):
        return {}


def _save_cache(path, cache):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(cache, ensure_ascii=False), encoding='utf-8')
    temp.replace(path)


def _hash_prompt(prompt: str, model: str, params: dict) -> str:
    body = json.dumps({'prompt':prompt,'model':model,'params':params},sort_keys=True,ensure_ascii=False)
    return hashlib.sha256(body.encode('utf-8')).hexdigest()


def _call_openai_compatible(provider: str, model: str, prompt: str, config: dict, params: dict):
    from openai import OpenAI
    if provider == 'groq':
        key = os.getenv('GROQ_API_KEY')
        if not key: raise RuntimeError('GROQ_API_KEY is not configured')
        client = OpenAI(api_key=key, base_url='https://api.groq.com/openai/v1', timeout=config['llm']['request_timeout_seconds'])
    else:
        client = OpenAI(api_key='ollama', base_url=config['models']['ollama_base_url'].rstrip('/') + '/v1', timeout=config['llm']['request_timeout_seconds'])
    kwargs = {'model':model,'messages':[{'role':'user','content':prompt}], 'temperature':params.get('temperature',config['llm']['temperature']), 'max_tokens':params.get('max_tokens',config['llm']['max_output_tokens'])}
    if params.get('json_mode'):
        kwargs['response_format']={'type':'json_object'}
    result = client.chat.completions.create(**kwargs)
    usage = result.usage
    return result.choices[0].message.content or '', int(usage.prompt_tokens if usage else 0), int(usage.completion_tokens if usage else 0)


def _call_gemini(model: str, prompt: str, config: dict, params: dict):
    from google import genai
    key = os.getenv('GEMINI_API_KEY')
    if not key: raise RuntimeError('GEMINI_API_KEY is not configured')
    client = genai.Client(api_key=key)
    generation = {'temperature':params.get('temperature',config['llm']['temperature']), 'max_output_tokens':params.get('max_tokens',config['llm']['max_output_tokens'])}
    if params.get('json_mode'):
        generation['response_mime_type']='application/json'
    response = client.models.generate_content(model=model, contents=prompt, config=generation)
    usage = getattr(response, 'usage_metadata', None)
    return response.text or '', int(getattr(usage,'prompt_token_count',0) or 0), int(getattr(usage,'candidates_token_count',0) or 0)


def _log(result: LLMResult):
    log_dir = ROOT / 'logs'
    log_dir.mkdir(parents=True, exist_ok=True)
    fields=asdict(result)
    fields.pop('content',None)
    row = {'request_id':str(uuid.uuid4()), **fields}
    with (log_dir / 'llm_calls.jsonl').open('a',encoding='utf-8') as f:
        f.write(json.dumps(row,ensure_ascii=False)+'\n')
    logger.info(json.dumps(row,ensure_ascii=False))


def generate(prompt: str, *, params: dict[str, Any] | None = None, model_override: str | None = None) -> LLMResult:
    """Generate text through Groq -> Gemini -> Ollama; cache successful responses on disk."""
    config = _config(); params = dict(params or {})
    model_map = {'groq':model_override or config['models']['groq_model'],'gemini':config['models']['gemini_model'],'ollama':config['models']['ollama_model']}
    cache_path = _cache_path(config); cache_key = _hash_prompt(prompt, json.dumps(model_map,sort_keys=True), params)
    with _LOCK:
        cache = _load_cache(cache_path)
        if cache_key in cache:
            stored = dict(cache[cache_key]); stored['cache_hit']=True; result = LLMResult(**stored)
            _log(result); return result
    errors=[]; delays=config['llm']['retry_delays_seconds']; start_all=time.perf_counter()
    for index, provider in enumerate(config['llm']['provider_order']):
        model=model_map[provider]
        if provider=='groq' and not os.getenv('GROQ_API_KEY'):
            errors.append('groq skipped: GROQ_API_KEY is not configured'); continue
        if provider=='gemini' and not os.getenv('GEMINI_API_KEY'):
            errors.append('gemini skipped: GEMINI_API_KEY is not configured'); continue
        for attempt in range(len(delays)+1):
            started=time.perf_counter()
            try:
                if provider in ('groq','ollama'):
                    content,tin,tout=_call_openai_compatible(provider,model,prompt,config,params)
                elif provider=='gemini':
                    content,tin,tout=_call_gemini(model,prompt,config,params)
                else:
                    raise RuntimeError(f'Unknown provider: {provider}')
                result=LLMResult(content=content,provider=provider,model=model,prompt_hash=cache_key,tokens_in=tin,tokens_out=tout,latency_ms=int((time.perf_counter()-started)*1000),fallback_used=index>0)
                with _LOCK:
                    cache=_load_cache(cache_path); cache[cache_key]=asdict(result); _save_cache(cache_path,cache)
                _log(result); return result
            except Exception as exc:
                errors.append(f'{provider} attempt {attempt+1}: {type(exc).__name__}: {exc}')
                if attempt < len(delays): time.sleep(delays[attempt])
    raise RuntimeError('All configured LLM providers failed: ' + ' | '.join(errors)) from None

