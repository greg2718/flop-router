"""Explicit Router-local Bench originals; opaque Scout references never open paths."""
import projection_contract as c

SCHEMA='router-bench-proof/v1'


def proofs_from_records(records):
    proofs={}
    for record in records:
        c.keys(record,{'schema','reference','artifact'})
        c.require(record['schema']==SCHEMA,'Unsupported proof envelope')
        ref=record['reference']; c.reference(ref,{'LOCAL_ARTIFACT'})
        body=record['artifact']; c.require(type(body) is dict,'Invalid original')
        c.require(len(c.canonical(body))<=65536 and c.digest(body)==ref['sha256'],'Original hash mismatch')
        schema=body.get('schema_version')
        c.require(schema in {'flop-verification-request/v1','flop-verification-result/v1'},'Unsupported original schema')
        c.string(body.get('request_id'))
        if schema=='flop-verification-request/v1':
            for field in ('requester_did','target_agent_did','routing_decision_id'): c.string(body.get(field))
            for field in ('routing_decision_hash','task_hash'): c.sha(body.get(field))
            if 'capability_id' in body: c.string(body['capability_id'])
        else:
            c.string(body.get('bench_did'))
            c.require(type(body.get('artifact_hashes')) is dict,'Invalid artifact hashes')
            c.sha(body['artifact_hashes'].get('request_sha256'))
            c.require(body.get('status') in {'PASS','FAIL'},'Unsupported result outcome')
            c.string(body.get('reproducibility'),True)
        c.require(type(body.get('independent_reputation')) is bool,'Explicit independence disclosure required')
        key=c.canonical(ref).decode()
        c.require(key not in proofs,'Duplicate proof reference')
        proofs[key]=body
    return proofs


def linked_outcomes(history, proofs):
    """Yield only independently linked local originals, with effective audit state.

    No producer CAPABILITY_USE claim enters this bridge. Missing originals or
    missing exact tested capability remain historical, unscored audit evidence.
    """
    import router as r
    for item in history:
        q=item['record']
        if q['qualification_type'] not in {'CONTROLLED_BENCH','OBJECTIVE_VALIDATION'}: continue
        if item['effective_status']!='VALID' or item['superseded_by'] is not None: continue
        if not r.DID_RE.fullmatch(q['subject_did']): continue
        if not (q['operator_group']==c.FAMILY and q['same_operator'] is True and q['independent_reputation'] is False): continue
        originals=[proofs.get(c.canonical(ref).decode()) for ref in q['provenance_refs']]
        if any(x is None for x in originals): continue
        requests=[x for x in originals if x.get('schema_version')=='flop-verification-request/v1']
        results=[x for x in originals if x.get('schema_version')=='flop-verification-result/v1']
        if len(requests)!=1 or len(results)!=1: continue
        request,result=requests[0],results[0]
        if not (result.get('request_id')==request.get('request_id')==q['claim']['id'] and q['claim']['kind']=='VERIFICATION'
                and result.get('artifact_hashes',{}).get('request_sha256')==c.digest(request)
                and request.get('target_agent_did')==q['subject_did']
                and request.get('requester_did') in {r.SCOUT_DID,r.BENCH_DID,r.ROUTER_DID}
                and result.get('bench_did')==r.BENCH_DID
                and request.get('independent_reputation') is False and result.get('independent_reputation') is False
                and result.get('status')==q['qualification_outcome']==q['correctness']
                and result.get('status') in {'PASS','FAIL'}
                and result.get('reproducibility')==q['reproducibility']=='DETERMINISTIC'): continue
        cap=request.get('capability_id')
        if cap not in {rule.capability_id for rule in r.CAPABILITY_RULES}: cap=None
        try:
            c.string(request.get('routing_decision_id'));c.sha(request.get('routing_decision_hash'));c.sha(request.get('task_hash'))
        except c.ProjectionError: continue
        # The source reference must bind this exact result, not a second artifact.
        if (q['source_ref']['sha256']!=c.digest(result) or
                proofs.get(c.canonical(q['source_ref']).decode()) != result): continue
        yield dict(target=q['subject_did'],capability=cap,key=c.digest([request['target_agent_did'],cap,c.digest(request)]),
            outcome=result['status'],request_id=request['request_id'],timestamp=q['qualified_at'],
            provenance='CONTROLLED_SAME_OPERATOR_VALIDATION:'+c.digest([c.digest(request),c.digest(result)]),
            same_operator=True,independent_reputation=False,
            workflow_status='CLOSED' if result['status']=='PASS' else 'REJECTED',
            closed_at=None,retention='PERMANENT_BENCH_VERIFICATION')


def controlled_results(history, proofs):
    for item in linked_outcomes(history, proofs):
        if item['capability'] is not None:
            yield item
