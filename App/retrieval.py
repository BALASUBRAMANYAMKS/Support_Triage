"""Hybrid dense + BM25 retrieval, RRF fusion and local cross-encoder reranking."""
from __future__ import annotations
import re, json, uuid
from datetime import datetime, timezone
from pathlib import Path
import chromadb
import yaml
from chromadb.utils.embedding_functions import SentenceTransformerEmbeddingFunction
from rank_bm25 import BM25Okapi
from sentence_transformers import CrossEncoder
from .pii import mask_sensitive_text

ROOT=Path(__file__).resolve().parents[1]
WORD=re.compile(r"[a-z0-9]+(?:[._-][a-z0-9]+)*",re.I)
DENSE_QUERY_PREFIX='Represent this sentence for searching relevant passages: '


def _config(): return yaml.safe_load((ROOT/'config.yaml').read_text(encoding='utf-8-sig'))

def _tokens(text): return WORD.findall((text or '').lower())

class RetrievalService:
    def __init__(self):
        self.cfg=_config(); self.embedding_name=self.cfg['models']['embedding']
        client=chromadb.PersistentClient(path=str(ROOT/self.cfg['app']['vector_store_path']))
        embed=SentenceTransformerEmbeddingFunction(model_name=self.embedding_name,device='cpu')
        self.collections={name:client.get_or_create_collection(name,embedding_function=embed) for name in ('kb_chunks','tickets')}
        self.reranker=CrossEncoder(self.cfg['models']['reranker'],device='cpu')
        self._bm25={}

    def _where(self,collection,filters):
        clauses=[]
        for key,value in (filters or {}).items(): clauses.append({key:value})
        if collection=='kb_chunks': clauses.append({'status':'Published'})
        return clauses[0] if len(clauses)==1 else {'$and':clauses} if clauses else None

    def _keyword_search(self,collection_name,query,where,k):
        collection=self.collections[collection_name]
        records=collection.get(where=where,include=['documents','metadatas']) if where else collection.get(include=['documents','metadatas'])
        ids=records.get('ids',[]); docs=records.get('documents',[]); metas=records.get('metadatas',[])
        if not docs: return []
        tokenized=[_tokens(doc) for doc in docs]
        bm25=BM25Okapi(tokenized)
        scores=bm25.get_scores(_tokens(query))
        order=sorted(range(len(scores)),key=lambda i:scores[i],reverse=True)[:k]
        return [{'id':ids[i],'text':docs[i],'metadata':metas[i],'bm25_score':float(scores[i]),'bm25_rank':rank+1} for rank,i in enumerate(order) if scores[i]>0]

    def _dense_search(self,collection_name,query,where,k):
        col=self.collections[collection_name]
        result=col.query(query_texts=[DENSE_QUERY_PREFIX+query],n_results=k,where=where,include=['documents','metadatas','distances'])
        rows=[]
        for rank,(cid,doc,meta,distance) in enumerate(zip(result['ids'][0],result['documents'][0],result['metadatas'][0],result['distances'][0]),1):
            rows.append({'id':cid,'text':doc,'metadata':meta,'dense_score':1-float(distance),'dense_rank':rank})
        return rows

    def search_collection(self,query,collection_name,filters=None,k=None):
        cfg=self.cfg['retrieval']; k=k or cfg['dense_k']; where=self._where(collection_name,filters)
        dense=self._dense_search(collection_name,query,where,k)
        keyword=self._keyword_search(collection_name,query,where,k)
        fused={}
        for result in dense:
            fused[result['id']]={**result,'rrf_score':0.0}
            fused[result['id']]['rrf_score']+=1/(cfg['rrf_constant']+result['dense_rank'])
        for result in keyword:
            target=fused.setdefault(result['id'],{**result,'rrf_score':0.0})
            target.update({key:value for key,value in result.items() if key not in target})
            target['rrf_score']+=1/(cfg['rrf_constant']+result['bm25_rank'])
        candidates=sorted(fused.values(),key=lambda item:item['rrf_score'],reverse=True)[:cfg['rerank_candidates']]
        if not candidates:return []
        pairs=[(query,item['text']) for item in candidates]
        scores=self.reranker.predict(pairs)
        for item,score in zip(candidates,scores): item['rerank_score']=float(score)
        candidates.sort(key=lambda item:item['rerank_score'],reverse=True)
        final=candidates[:cfg['final_k']]
        log={'request_id':str(uuid.uuid4()),'timestamp':datetime.now(timezone.utc).isoformat(),'query':mask_sensitive_text(query),'collection':collection_name,
             'dense':[{'id':x['id'],'score':x.get('dense_score')} for x in dense],
             'bm25':[{'id':x['id'],'score':x.get('bm25_score')} for x in keyword],
             'fused':[{'id':x['id'],'score':x.get('rrf_score')} for x in sorted(fused.values(),key=lambda z:z['rrf_score'],reverse=True)[:cfg['rerank_candidates']]],
             'reranked':[{'id':x['id'],'score':x.get('rerank_score')} for x in final]}
        path=ROOT/'logs'/'retrieval.jsonl'; path.parent.mkdir(parents=True,exist_ok=True)
        with path.open('a',encoding='utf-8') as handle: handle.write(json.dumps(log,ensure_ascii=False)+'\n')
        return final

    def ablation(self,query,filters=None):
        """Return top-five dense, hybrid RRF, and hybrid-plus-rerank KB results."""
        cfg=self.cfg['retrieval']; where=self._where('kb_chunks',filters or {'audience':'end_user'})
        dense=self._dense_search('kb_chunks',query,where,cfg['dense_k'])
        keyword=self._keyword_search('kb_chunks',query,where,cfg['bm25_k'])
        dense_top=sorted(dense,key=lambda x:x.get('dense_score',0),reverse=True)[:cfg['final_k']]
        fused={}
        for item in dense:
            fused[item['id']]={**item,'rrf_score':1/(cfg['rrf_constant']+item['dense_rank'])}
        for item in keyword:
            target=fused.setdefault(item['id'],{**item,'rrf_score':0.0})
            target['rrf_score']+=1/(cfg['rrf_constant']+item['bm25_rank'])
        hybrid=sorted(fused.values(),key=lambda x:x['rrf_score'],reverse=True)[:cfg['final_k']]
        reranked=sorted(hybrid,key=lambda x:x.get('rerank_score',0),reverse=True)
        if hybrid:
            scores=self.reranker.predict([(query,x['text']) for x in hybrid])
            for item,score in zip(hybrid,scores): item['rerank_score']=float(score)
            reranked=sorted(hybrid,key=lambda x:x['rerank_score'],reverse=True)
        return {'dense_only':dense_top,'hybrid':hybrid,'hybrid_reranked':reranked[:cfg['final_k']]}

    def chatbot(self,query,k=None):
        return self.search_collection(query,'kb_chunks',{'audience':'end_user'},k)

    def triage_kb(self,query,k=None):
        return self.search_collection(query,'kb_chunks',{},k)

    def similar_tickets(self,query,k=None):
        return self.search_collection(query,'tickets',{},k or self.cfg['retrieval']['similar_tickets'])

    def retrieve(self,query,filters=None,k=None):
        """Compatibility signature: filters may select doc_type and audience."""
        filters=filters or {}; doc_type=filters.pop('doc_type',None)
        if doc_type=='ticket': return self.similar_tickets(query,k)
        if filters.get('audience')=='end_user': return self.chatbot(query,k)
        return self.triage_kb(query,k)
