"""Exact synthetic decision counterexamples; rational arithmetic, no fitting."""
from fractions import Fraction as F
from itertools import product
import json


def choose(energies):
    return min(energies, key=lambda k: (energies[k], k))


def risk(states, posterior):
    """Bayes simple regret using all available posterior information."""
    mass = sum(states[i][0] for i in posterior)
    expected = {a: sum(states[i][0] * states[i][1][a] for i in posterior) / mass
                for a in states[0][1]}
    selected = choose(expected)
    value = sum(states[i][0] * (states[i][1][selected] - min(states[i][1].values()))
                for i in posterior) / mass
    return value, selected


def outcomes(states, posterior, query):
    result = {}
    for i in posterior:
        result.setdefault(states[i][1][query], []).append(i)
    return result.values()


def after_query_risk(states, posterior, query):
    mass = sum(states[i][0] for i in posterior)
    return sum(sum(states[i][0] for i in group) / mass * risk(states, group)[0]
               for group in outcomes(states, posterior, query))


def run():
    ex1 = []
    for b, pb in [(F(-2), F(1, 4)), (F(2), F(3, 4))]:
        for c in [F(4), F(16)]:
            ex1.append((pb / 2, {'A': F(0), 'B': b, 'C': c}))
    ids = list(range(len(ex1)))
    before = risk(ex1, ids)[0]
    query_risks = {a: after_query_risk(ex1, ids, a) for a in ['B', 'C']}
    assert before == F(1, 2)
    assert query_risks == {'B': F(0), 'C': F(1, 2)}
    variances = {a: sum(p*e[a]*e[a] for p,e in ex1) - sum(p*e[a] for p,e in ex1)**2
                 for a in ['B', 'C']}
    assert variances == {'B': F(3), 'C': F(36)}

    ex2 = []
    for u,v in product(range(2), repeat=2):
        e = {'A': F(0), 'P': F(10+u), 'Q': F(12+v)}
        for x,y in product(range(2), repeat=2):
            e[f'T{x}{y}'] = F(-1 if (u,v)==(x,y) else 3)
        ex2.append((F(1,4), e))
    ids2 = list(range(len(ex2)))
    before2 = risk(ex2, ids2)[0]
    one = {a: after_query_risk(ex2, ids2, a) for a in ['P', 'Q', 'T00']}
    assert before2 == 1
    assert one == {'P': F(1), 'Q': F(1), 'T00': F(3,4)}
    pair = {}
    for a,b in [('P','Q'), ('T00','T01'), ('T00','P')]:
        pair[a+' then '+b] = sum(sum(ex2[i][0] for i in group) * after_query_risk(ex2, group, b)
                                  for group in outcomes(ex2, ids2, a))
    assert pair['P then Q'] == 0
    assert pair['T00 then T01'] == F(1,2)
    assert pair['T00 then P'] == F(1,2)
    # Best-queried-only endpoint: probe then identified target beats greedy EI.
    # A is already reference-known at energy zero; two additional calls remain.
    probe_rows = []
    greedy_regret = F(0)
    probe_regret = F(0)
    for hidden in range(4):
        energies = {'A': F(0), 'P': F(10+hidden)}
        energies.update({f'T{i}': F(-10 if i == hidden else 3) for i in range(4)})
        greedy_regret += F(1,4) * (min(energies['A'], energies['T0'], energies['T1']) + 10)
        probe_regret += F(1,4) * (min(energies['A'], energies['P'], energies[f'T{hidden}']) + 10)
        probe_rows.append(energies)
    assert greedy_regret == 5 and probe_regret == 0
    return {
        'classification': 'executed synthetic exact finite enumeration',
        'highest_uncertainty_is_wrong': {
            'baseline_risk':str(before), 'candidate_variance':{k:str(v) for k,v in variances.items()},
            'post_query_risk':{k:str(v) for k,v in query_risks.items()},
            'cost_per_query': '1/10', 'net_query_value': {k:str(before-v-F(1,10)) for k,v in query_risks.items()}},
        'best_queried_one_step_failure':{
            'baseline_risk':'10', 'each_target_myopic_improvement':'5/2',
            'probe_myopic_improvement':'0', 'greedy_two_target_risk':str(greedy_regret),
            'probe_then_identified_target_risk':str(probe_regret), 'same_additional_queries':2,
            'query_cost':'1/10', 'greedy_fixed_two_call_total_loss':'26/5', 'lookahead_total_loss':'1/5',
            'greedy_early_stop_expected_calls':'7/4', 'greedy_early_stop_total_loss':'207/40',
            'assumption':'known four-state joint prior; P=10+hidden target ID; terminal chooses best queried; A already observed at zero'},
        'one_step_failure':{
            'baseline_risk':str(before2), 'post_query_risk':{k:str(v) for k,v in one.items()},
            'post_two_query_risk':{k:str(v) for k,v in pair.items()},
            'query_cost':'1/10', 'greedy_two_step_total_loss':'7/10',
            'two_probe_total_loss':'1/5',
            'assumption':'exact known joint discrete prior; energy labels are deterministic conditional on latent bits; terminal may accept an unqueried candidate given posterior evidence'}
    }

if __name__ == '__main__':
    print(json.dumps(run(), indent=2))
