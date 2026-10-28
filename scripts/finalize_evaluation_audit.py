"""Publish Codex's recorded source-text spot check, preserving Jev's raw decisions.

The notes below are review judgments made after reading the original extracted
paper text. This script only attaches provenance and formats those recorded notes.
"""
import gzip
import hashlib
import json
from collections import Counter
from pathlib import Path

from mentions.evaluations import POLICY_SHA, adjudicate, verified_outcome

# paper id, model id, source judgment, reviewed outcome (if resolved), source
# line spans, and a paraphrase of the source evidence. No generated model is
# invoked by this script.
REVIEWS = [
    ('2605.09948', 'gr00t_n1_5', 'unresolved', 'uncertain_baseline', [[515,519]], 'Some baselines are reported from or reproduced following a harness; GR00T N1.5 is not assigned an unambiguous run provenance.'),
    ('2609.18651', 'pi05', 'evaluated', 'beaten', [[294,314]], 'Table II reports original and task-adapted pi0.5 in the authors\' real peg and cup experiments; full FIERCE reports higher success on both.'),
    ('2605.01448', 'openvla', 'unresolved', 'uncertain_baseline', [[350,368],[374,419]], 'OpenVLA appears in AGNOSTOS comparison rows; the reviewed text does not distinguish copied benchmark scores from an author-run OpenVLA experiment.'),
    ('2606.01095', 'xvla', 'evaluated', 'no_proposed_method', [[352,364],[441,448]], 'The diagnostics study explicitly evaluates seven policies on its GPU and reports X-VLA computational measurements; it proposes no competing robot policy.'),
    ('2502.15613', 'dp3', 'evaluated', 'beaten', [[422,450],[480,502]], 'The baseline setting explicitly implements Diffusion Policy 3D and validates each method five times per gripper; the proposed method has higher aggregate success.'),
    ('2605.11832', 'xvla', 'unresolved', 'uncertain_baseline', [[447,476],[558,568]], 'X-VLA has comparison scores, but the reviewed protocol does not establish which X-VLA rows the authors reran.'),
    ('2603.28427', 'diffusion_policy', 'evaluated', 'beaten', [[538,547],[576,590]], 'The authors test shared-autonomy variants with DP and DP3; the named DP baseline scores 60% success versus 73.3% for the proposed variant.'),
    ('2504.18904', 'octo', 'evaluated', 'no_proposed_method', [[564,590],[669,679]], 'The benchmark explicitly fine-tunes Octo and evaluates it on synthetic and real grasping tasks. No new competing policy is proposed.'),
    ('2604.09651', 'pi0', 'evaluated', 'unclear', [[342,369],[960,969]], 'A clean pi0 baseline is measured against attacked policies; the authors also train and deploy it in real experiments. Attack success is not general policy superiority.'),
    ('2412.14058', 'rt2_x', 'unresolved', 'uncertain_baseline', [[1448,1463]], 'The SimplerEnv table contains RT-2-X results; model-specific evidence that these authors executed RT-2-X is not established by the reviewed passages.'),
    ('2607.04988', 'pi05', 'evaluated', 'mixed', [[667,678],[859,873]], 'All real-world methods are fine-tuned on the same demonstrations and evaluated under an identical randomized protocol, explicitly including pi0.5. Published scores in other tables do not negate these runs.'),
    ('2607.29172', 'gemini_robotics', 'not_evaluated', 'not_baseline', [[150,156],[421,426]], 'The evaluated model is Gemini Robotics On-Device, a distinct release. These runs cannot be credited to the original Gemini Robotics row.'),
    ('2609.12075', 'smolvla', 'evaluated', 'unclear', [[661,670]], 'SmolVLA is explicitly measured as one of four serving workloads on the authors\' hardware. The competing methods are serving systems, so this establishes direct evaluation but not a robot-policy win.'),
    ('2609.22684', 'smolvla', 'unresolved', 'uncertain_baseline', [[452,488],[502,522]], 'SmolVLA appears in the LIBERO comparison, but the authors\' own training and real-robot descriptions identify StateMem and other models rather than a SmolVLA rerun.'),
    ('2407.19819', 'diffusion_policy', 'not_evaluated', 'not_baseline', [[330,345],[375,389]], 'Diffusion Policy is trained to supply trajectories for anomaly detection; the compared models are detectors. The released policy is not separately evaluated as a comparator or diagnostic target.'),
    ('2606.05979', 'pi05', 'evaluated', 'unclear', [[388,412]], 'The real-robot protocol explicitly trains all named models for 50k steps and runs pi0.5 success and latency experiments. Comparable success and task-specific gains do not establish a universal win.'),
    ('2506.16652', 'dp3', 'not_evaluated', 'not_baseline', [[550,560],[838,841]], 'DP3 motivates robust point-cloud inputs; the implemented comparators are Lang-DP variants, not the released DP3 model.'),
    ('2605.05714', 'rt2_x', 'not_evaluated', 'not_baseline', [[849,852]], 'The RT-X dataset/model work is a citation; it is not an executed RT-2-X comparator.'),
    ('2609.35575', 'pi0', 'not_evaluated', 'not_baseline', [[580,587]], 'The original pi0 work is cited; this does not establish an experimental run of that release.'),
    ('2503.01238', 'rt2', 'not_evaluated', 'not_baseline', [[279,288],[582,584]], 'RT-2 illustrates a prior generalization taxonomy and is referenced; the paper does not run RT-2.'),
    ('2604.01259', 'palm_e', 'not_evaluated', 'not_baseline', [[924,930]], 'PaLM-E is a background reference in an autonomous-driving benchmark, with no executed PaLM-E model evaluation.'),
    ('2609.34968', 'spatialvla', 'not_evaluated', 'not_baseline', [[1096,1101]], 'SpatialVLA is a cited prior model, not an executed comparator in the reviewed experiment.'),
    ('2510.00814', 'act', 'not_evaluated', 'not_baseline', [[99,108],[313,319]], 'The method builds a modified mesh policy on ACT; that architecture inheritance is not a separate baseline evaluation of ACT.'),
    ('2507.12440', 'lapa', 'not_evaluated', 'not_baseline', [[781,786]], 'Latent action pretraining is referenced as prior work, without a separately executed LAPA comparator.'),
    ('2602.22088', 'gr00t_n1', 'not_evaluated', 'not_baseline', [[710,717]], 'GR00T N1 is a background citation in a force-position policy study, not an executed comparison.'),
    ('2307.05973', 'rt1', 'not_evaluated', 'not_baseline', [[624,630]], 'VoxPoser references RT-1; the cited release is not directly evaluated in this paper.'),
    ('2608.05042', 'tracevla', 'not_evaluated', 'not_baseline', [[1088,1095]], 'TraceVLA is referenced in the memory-related literature without a model run.'),
    ('2604.17896', 'pi0', 'not_evaluated', 'not_baseline', [[572,581]], 'The pi0 reference supplies background; it is not an evaluated instance of the original release.'),
    ('2507.06174', 'gr00t_n1', 'not_evaluated', 'not_baseline', [[1490,1497]], 'GR00T N1 is a citation in a teleoperation-control study, not an executed model baseline.'),
    ('2608.10860', 'octo', 'not_evaluated', 'not_baseline', [[2337,2348]], 'Octo appears as a reference model in the benchmark table; no Octo-specific author-run protocol is established.'),
    ('2501.06994', 'dp3', 'not_evaluated', 'not_baseline', [[445,451]], 'The DP3 reference is present, but a released DP3 model is not separately run as a comparator.'),
    ('2606.01847', 'gr00t_n1', 'not_evaluated', 'not_baseline', [[657,664]], 'GR00T N1 is cited as prior foundation-model work, not executed as an experimental target.'),
    ('2602.12032', 'rdt_1b', 'not_evaluated', 'not_baseline', [[351,360]], 'The Mask baseline adapts RDT-1B\'s masking idea; it does not evaluate the RDT-1B model.'),
    ('2505.15685', 'gemini_robotics', 'not_evaluated', 'not_baseline', [[246,258],[632,639]], 'Gemini Robotics is described as a representative system; the grounding experiment evaluates other named models.'),
    ('2608.29896', 'lingbot_vla', 'not_evaluated', 'not_baseline', [[1020,1037]], 'The RoboDojo caption states that baseline results are reproduced from its public leaderboard; this is score reporting rather than an author-run LingBot experiment.'),
    ('2508.17449', 'dp3', 'not_evaluated', 'not_baseline', [[894,917]], 'The survey compiles benchmark results from official papers; a DP3 score in the table does not establish a new run.'),
    ('2509.03383', 'rt2', 'not_evaluated', 'not_baseline', [[908,916]], 'RT-2 is a related-work citation; the reviewed experiment does not execute that model.'),
    ('2609.37721', 'openvla', 'not_evaluated', 'not_baseline', [[1374,1383]], 'The actual experimental comparator is OpenVLA-OFT. It must not also count as evaluation of the base OpenVLA release.'),
    ('2609.05533', 'xvla', 'unresolved', 'uncertain_baseline', [[478,489]], 'X-VLA is present in a comparison table, but the original excerpts and reviewed setup do not establish that this model was run by these authors.'),
    ('2603.06749', 'dp3', 'not_evaluated', 'not_baseline', [[3714,3718]], 'This industrial-foundation-model survey references DP3; it does not supply evidence of a new DP3 experiment.'),
    ('2309.16699', 'pi0', 'not_evaluated', 'not_baseline', [[134,155]], 'The apparent model alias is mathematical pi notation in rotation matrices, not a released robot model.'),
    ('2312.04224', 'pi07', 'not_evaluated', 'not_baseline', [[233,246]], 'The apparent pi0.7 mention is a typeset hydrodynamic equation, not the robot-policy release.'),
    ('2406.18699', 'diffusion_policy', 'not_evaluated', 'not_baseline', [[812,820]], 'Diffusion Policy appears in a reference; the study does not execute that model as a baseline.'),
    ('2409.08507', 'pi0', 'not_evaluated', 'not_baseline', [[428,449]], 'The apparent model mention is state/control notation in a classical guidance paper.'),
    ('2506.19597', 'act', 'not_evaluated', 'not_baseline', [[229,240],[434,436]], 'The study evaluates LiDAR perception methods and references action chunking; it does not evaluate ACT.'),
    ('2603.07663', 'act', 'not_evaluated', 'not_baseline', [[107,115],[339,355]], 'ACT motivates imitation-learning architecture; the tested policy is the authors\' phase-aware DAISS method, not a standalone ACT comparator.'),
    ('2609.36151', 'gr00t_n1', 'not_evaluated', 'not_baseline', [[389,420],[548,551]], 'GR00T N1 is a wrapped bibliography entry. The actual controller comparators are SONIC and compliance-control variants.'),
]


def main():
    sample = json.loads(Path('data/evaluations/audit-sample.json').read_text())
    sample_map = {(r['paper_id'], r['model_id']): r for r in sample['sample']}
    with gzip.open('data/evaluations/audit-text.jsonl.gz', 'rt') as handle:
        texts = {r['paper_id']: r['text'] for r in map(json.loads, handle)}
    decisions = {r['paper_id']: r for r in map(json.loads, Path('data/evaluations/jev.jsonl').read_text().splitlines())}
    verification = {r['paper_id']: r for r in map(json.loads, Path('data/evaluations/verification.jsonl').read_text().splitlines())}
    reviews = []
    for pid, mid, status, reviewed_outcome, spans, note in REVIEWS:
        case = dict(sample_map[(pid, mid)])
        raw = decisions[pid]
        machine_outcome = verified_outcome(raw, mid, verification.get(pid, {}))
        case.update(source_judgment=status, reviewed_outcome=reviewed_outcome, source_lines=spans,
                    source_text_sha256=hashlib.sha256(texts[pid].encode()).hexdigest(),
                    note=note, initial_outcome=adjudicate(raw, mid), verified_machine_outcome=machine_outcome,
                    changed_by_source_review=machine_outcome != reviewed_outcome,
                    source_url=f'https://arxiv.org/abs/{pid}')
        reviews.append(case)
    if len(reviews) != len(sample_map) or len({(r['paper_id'], r['model_id']) for r in reviews}) != len(reviews):
        raise ValueError('Audit does not exactly cover the selected sample')
    report = dict(schema=1, reviewer='Codex agent source-text review; not a human review or independent replication',
                  source_review_completed=True,
                  classification_policy_sha256=POLICY_SHA, sampling=sample['strategy'], seed=sample['seed'],
                  papers=len({r['paper_id'] for r in reviews}), cases=len(reviews),
                  source_judgments=dict(Counter(r['source_judgment'] for r in reviews)),
                  changed_by_source_review=sum(r['changed_by_source_review'] for r in reviews),
                  limitation='A small stratified spot check is not an estimate of corpus-wide accuracy. Unresolved provenance remains excluded.',
                  reviews=reviews)
    path = Path('output/evaluations/audit.json')
    path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + '\n')
    print(json.dumps({k: report[k] for k in ['papers','cases','source_judgments','changed_by_source_review']}, indent=2))


if __name__ == '__main__':
    main()
