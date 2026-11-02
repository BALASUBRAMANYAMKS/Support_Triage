"""Structure-aware ingestion into persistent local Chroma collections.
Only KB articles and resolved history are ingested; held-out test files are never read.
"""
from __future__ import annotations
import hashlib, json, re
from pathlib import Path
import chromadb
from chromadb.utils.embedding_functions import SentenceTransformerEmbeddingFunction
import yaml

ROOT=Path(__file__).resolve().parents[1]
TOKEN_RE=re.compile(r"\S+")
SECTION_RE=re.compile(r"(?m)^##\s+(.+?)\s*$")


def config():
    return yaml.safe_load((ROOT/'config.yaml').read_text(encoding='utf-8-sig'))


def token_chunks(text: str, limit: int=400, overlap_ratio: float=.15):
    tokens=TOKEN_RE.findall(text)
    if not tokens: return []
    overlap=max(1,int(limit*overlap_ratio)); step=max(1,limit-overlap)
    return [' '.join(tokens[i:i+limit]) for i in range(0,len(tokens),step)]


def kb_section_chunks(article: dict, markdown: str, limit: int, overlap_ratio: float):
    matches=list(SECTION_RE.finditer(markdown))
    chunks=[]
    if not matches:
        return chunks
    for section_index,match in enumerate(matches):
        start=match.end(); end=matches[section_index+1].start() if section_index+1<len(matches) else len(markdown)
        section=match.group(1).strip(); body=markdown[start:end].strip()
        prefix=f"{article['title']} | {section}: "
        for part_index,part in enumerate(token_chunks(body,limit,overlap_ratio)):
            text=prefix+part
            stable=f"kb:{article['kb_id']}:{section}:{part_index}:{hashlib.sha1(text.encode('utf-8')).hexdigest()[:10]}"
            chunks.append((stable,text,{
                'doc_type':'kb','source_id':article['kb_id'],'title':article['title'],'section':section,
                'category':article['category'],'subcategory':article['subcategory'],
                'affected_ci':article['applies_to'][0] if article['applies_to'] else '',
                'audience':article['audience'],'status':article['status'],
                'last_reviewed':article['last_reviewed']
            }))
    return chunks


def ticket_document(ticket: dict):
    resolution=ticket.get('resolution_notes') or ''
    text='\n'.join(x for x in [ticket.get('short_description',''),ticket.get('description',''),resolution] if x)
    metadata={
        'doc_type':'ticket','source_id':ticket['ticket_id'],'section':'ticket and resolution',
        'category':ticket.get('category') or '', 'subcategory':ticket.get('subcategory') or '',
        'affected_ci':ticket.get('affected_ci') or '', 'audience':'agent',
        'status':ticket.get('status') or '', 'last_reviewed':'',
        'priority':ticket.get('priority') or '',
        'assignment_group':ticket.get('assignment_group') or '',
        'resolved_at':ticket.get('resolved_at') or ''
    }
    stable='ticket:'+ticket['ticket_id']
    return stable,text,metadata


def get_lines(path: Path):
    if not path.exists(): return []
    return [json.loads(line) for line in path.read_text(encoding='utf-8-sig').splitlines() if line.strip()]


def ingest():
    cfg=config(); model=cfg['models']['embedding']; store=ROOT/cfg['app']['vector_store_path']
    store.mkdir(parents=True,exist_ok=True)
    client=chromadb.PersistentClient(path=str(store))
    embedding=SentenceTransformerEmbeddingFunction(model_name=model,device='cpu')
    kb_collection=client.get_or_create_collection('kb_chunks',embedding_function=embedding,metadata={'hnsw:space':'cosine'})
    ticket_collection=client.get_or_create_collection('tickets',embedding_function=embedding,metadata={'hnsw:space':'cosine'})
    index=json.loads((ROOT/'data'/'kb_index.json').read_text(encoding='utf-8-sig'))
    limit=cfg['retrieval']['chunk_tokens']; overlap=cfg['retrieval']['chunk_overlap_ratio']
    kb_count=0
    for article in index:
        source=article['kb_id']
        md=(ROOT/'data'/article['path']).read_text(encoding='utf-8-sig')
        chunks=kb_section_chunks(article,md,limit,overlap)
        kb_collection.delete(where={'source_id':source})
        if chunks:
            ids,texts,metas=zip(*chunks)
            kb_collection.upsert(ids=list(ids),documents=list(texts),metadatas=list(metas))
            kb_count+=len(chunks)
    history=get_lines(ROOT/'data'/'tickets_history.jsonl'); ticket_count=0
    for ticket in history:
        record=ticket_document(ticket)
        ticket_collection.delete(where={'source_id':ticket['ticket_id']})
        ticket_collection.upsert(ids=[record[0]],documents=[record[1]],metadatas=[record[2]])
        ticket_count+=1
    print(f'Ingested {kb_count} KB chunks and {ticket_count} history tickets into {store}')
    print('The hidden test set and gold labels were not accessed.')

if __name__=='__main__': ingest()
