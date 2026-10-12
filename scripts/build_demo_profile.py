#!/usr/bin/env python3
"""Build a realistic demo profile for the README screenshots.

Not a test fixture. `seed_multi_dimensional` says of itself that its contents
are "chosen to be the ones a dimensional query can get wrong, not to look
realistic" -- which is right for a test and wrong for a screenshot. This builds
the other thing: an exam that looks like a student six weeks into Step 1
preparation, with real published weight ranges, entries spread over real dates,
and reflections written as a person would write them.

Everything here is invented study content. No personal data.

Usage:
    python build_demo_profile.py <app_data_dir>
"""
from __future__ import annotations

import random
import sys
from datetime import date, timedelta
from pathlib import Path

# This file lives in <repo>/scripts/, so the repository root is its parent's
# parent. Derived rather than written down: an absolute path here would be one
# machine's layout, and on the maintainer's box it would also be a personal
# path, which the publish scan refuses to put in the public tree.
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "src"))

from database.master_db import MasterDatabase          # noqa: E402
from database.user_db import UserDatabase              # noqa: E402

EXAM = "USMLE Step 1"

# Real 2025 Step 1 published ranges. They deliberately do not sum to 100%:
# the two axes are overlapping partitions of one item pool, which is the
# thing #64 exists to surface rather than correct.
SYSTEMS = [
    ("Blood & Lymphoreticular/Immune Systems", 7, 11, [
        "Anemias", "Leukemias & Lymphomas", "Coagulation Disorders",
        "Hypersensitivity Reactions", "Immunodeficiencies"]),
    ("Behavioral Health & Nervous System", 9, 13, [
        "Seizure Disorders", "Cerebrovascular Disease", "Demyelinating Disease",
        "Mood Disorders", "Neurodegenerative Disease"]),
    ("Respiratory & Renal/Urinary Systems", 9, 13, [
        "Acid-Base Disorders", "Obstructive Lung Disease", "Glomerular Disease",
        "Acute Kidney Injury", "Pulmonary Vascular Disease"]),
    ("Musculoskeletal, Skin & Subcutaneous Tissue", 6, 10, [
        "Inflammatory Arthritis", "Muscle Disorders", "Bullous Skin Disease"]),
    ("Multisystem Processes & Disorders", 6, 10, [
        "Sepsis & Shock", "Fluid & Electrolyte Disorders", "Nutritional Deficiency"]),
    ("Cardiovascular System", 5, 9, [
        "Heart Failure", "Ischemic Heart Disease", "Valvular Disease",
        "Arrhythmias", "Hypertension"]),
    ("Gastrointestinal System", 4, 8, [
        "Liver Disease", "Malabsorption", "Inflammatory Bowel Disease"]),
    ("Endocrine System", 4, 8, [
        "Diabetes Mellitus", "Thyroid Disorders", "Adrenal Disorders"]),
    ("Social Sciences", 6, 9, [
        "Communication Skills", "Medical Ethics"]),
    ("Biostatistics & Epidemiology", 4, 6, [
        "Study Design", "Diagnostic Testing", "Measures of Association"]),
    ("Human Development", 1, 3, ["Embryology"]),
]

DISCIPLINES = [
    ("Pathology", 44, 52, ["Neoplasia", "Inflammation & Repair", "Cell Injury"]),
    ("Physiology", 25, 35, ["Cardiac Physiology", "Renal Physiology", "Respiratory Physiology"]),
    ("Pharmacology", 15, 22, ["Autonomic Agents", "Antimicrobials", "Cardiovascular Drugs"]),
    ("Biochemistry & Nutrition", 14, 24, ["Metabolism", "Molecular Biology", "Vitamins"]),
    ("Gross Anatomy & Embryology", 11, 15, ["Thorax & Abdomen", "Head & Neck"]),
    ("Microbiology", 10, 15, ["Bacteriology", "Virology", "Mycology & Parasitology"]),
    ("Histology & Cell Biology", 8, 13, ["Epithelia & Connective Tissue"]),
    ("Behavioral Sciences", 8, 13, ["Psychopathology", "Substance Use"]),
    ("Immunology", 6, 11, ["Adaptive Immunity", "Innate Immunity"]),
    ("Genetics", 5, 9, ["Inheritance Patterns", "Chromosomal Disorders"]),
]

# (topic, what I picked, what was right, why the right one is right,
#  what I got wrong about my own thinking, difficulty, seconds, error types)
ENTRIES = [
    ("Acid-Base Disorders", "Respiratory alkalosis", "Metabolic acidosis with respiratory compensation",
     "The pH is low and the bicarbonate is low. A low bicarbonate with a low pH is a metabolic acidosis; the low pCO2 is Winter's-formula compensation, not a second primary disorder.",
     "I read the low pCO2 first and stopped there. I need to go pH, then the matching value, then compensation, in that order, every time.",
     3, 95, ["Wrong Approach"]),
    ("Acid-Base Disorders", "Anion gap 8", "Anion gap 22",
     "Na minus chloride minus bicarbonate. I subtracted the potassium as well, which is not in the standard formula.",
     "Arithmetic, not knowledge. I know this formula cold and still got it wrong because I did it in my head while the clock was visible.",
     2, 48, ["Calculation Error", "Time Pressure"]),
    ("Glomerular Disease", "Minimal change disease", "Focal segmental glomerulosclerosis",
     "Nephrotic syndrome in an adult with HIV and a history of heroin use. Minimal change is the child's answer; FSGS is the adult one and the HIV association is near-diagnostic.",
     "I pattern-matched nephrotic syndrome to minimal change without reading past the first line of the stem.",
     3, 72, ["Misread Question"]),
    ("Glomerular Disease", "Post-streptococcal glomerulonephritis", "IgA nephropathy",
     "Hematuria one to two days after an upper respiratory infection is IgA nephropathy. Post-streptococcal disease comes two to three weeks later.",
     "I knew both of these. The interval is the whole discriminator and I did not look for it.",
     2, 61, ["Knowledge Gap"]),
    ("Acute Kidney Injury", "Prerenal azotemia", "Acute tubular necrosis",
     "FENa above 2% and muddy brown casts. Prerenal would give FENa below 1% with bland sediment.",
     "I committed to prerenal from the hypotension in the history and then read the labs looking for agreement instead of reading them.",
     3, 88, ["Wrong Approach"]),
    ("Heart Failure", "Systolic dysfunction", "Diastolic dysfunction with preserved ejection fraction",
     "Ejection fraction of 60% with signs of failure. A normal EF with failure symptoms is diastolic dysfunction.",
     "The EF was in the stem and I skimmed past the number.",
     2, 54, ["Misread Question"]),
    ("Heart Failure", "Furosemide", "Spironolactone",
     "The question asks what improves mortality in this class of heart failure. Loop diuretics relieve symptoms; aldosterone antagonists change survival.",
     "I answered what I would give, not what the question asked. Symptom relief and mortality benefit are different questions.",
     3, 70, ["Misread Question"]),
    ("Ischemic Heart Disease", "Unstable angina", "NSTEMI",
     "Troponin was elevated. Elevated troponin moves it out of unstable angina by definition, whatever the ECG shows.",
     "I anchored on the lack of ST elevation and treated that as the whole classification.",
     2, 58, ["Wrong Approach"]),
    ("Ischemic Heart Disease", "Left anterior descending", "Right coronary artery",
     "Inferior leads II, III and aVF. Those are the right coronary artery territory.",
     "Pure recall and I had it backwards. Worth a drawing rather than another read.",
     2, 40, ["Memory Failure"]),
    ("Arrhythmias", "Atrial fibrillation", "Atrial flutter",
     "A regular narrow-complex rhythm at 150 with sawtooth waves is flutter with 2:1 conduction. Fibrillation is irregularly irregular.",
     "I saw a fast narrow-complex rhythm and answered before checking whether it was regular.",
     3, 66, ["Careless Mistake"]),
    ("Hypertension", "Essential hypertension", "Fibromuscular dysplasia",
     "A young woman with new severe hypertension and an abdominal bruit. The string-of-beads appearance on imaging confirms it.",
     "The age and the bruit were both there. I defaulted to the common answer because the common answer is usually right.",
     3, 79, ["Wrong Approach"]),
    ("Hypertension", "Start lisinopril", "Check renal artery imaging",
     "The question asks for the next diagnostic step, not treatment.",
     "Second time this week I have answered the treatment question when the stem asked for a diagnostic one.",
     2, 44, ["Misread Question"]),
    ("Diabetes Mellitus", "Type 1 diabetes", "Maturity-onset diabetes of the young",
     "Three generations affected, onset before 25, no antibodies and no obesity. That pattern is autosomal dominant MODY.",
     "I did not register the family history as a finding. In a genetics stem it is the finding.",
     4, 110, ["Knowledge Gap"]),
    ("Diabetes Mellitus", "Give insulin alone", "Give insulin with potassium replacement",
     "Total body potassium is depleted in DKA even when the serum value reads normal. Insulin drives it intracellularly and will drop it further.",
     "I knew this fact and still picked the incomplete answer because it was the first plausible one.",
     3, 68, ["Incomplete Solution"]),
    ("Thyroid Disorders", "Graves disease", "Subacute granulomatous thyroiditis",
     "A tender thyroid after a viral illness with low radioiodine uptake. Graves has high uptake and a painless gland.",
     "I never looked at the uptake value. It is the single discriminator in this family of questions.",
     3, 82, ["Wrong Approach"]),
    ("Adrenal Disorders", "Primary adrenal insufficiency", "Secondary adrenal insufficiency",
     "Potassium was normal and there was no hyperpigmentation. Both point away from a primary adrenal cause.",
     "I treated hyponatremia as sufficient to localise the lesion. It is not.",
     3, 75, ["Misunderstanding"]),
    ("Anemias", "Iron deficiency anemia", "Anemia of chronic disease",
     "Low iron with low TIBC and a normal or high ferritin. Iron deficiency raises TIBC and drops ferritin.",
     "I stopped at the low serum iron. TIBC and ferritin are what separate these two and I skipped both.",
     2, 63, ["Incomplete Solution"]),
    ("Anemias", "Folate deficiency", "Vitamin B12 deficiency",
     "Neurological signs were present. Both cause a macrocytic anemia; only B12 deficiency causes subacute combined degeneration.",
     "I saw the macrocytosis and answered. The neuro exam was two lines further down.",
     2, 51, ["Careless Mistake"]),
    ("Leukemias & Lymphomas", "Hodgkin lymphoma", "Burkitt lymphoma",
     "A starry-sky pattern on biopsy with a jaw mass in a child. The t(8;14) MYC translocation confirms it.",
     "I recognised the starry sky and then picked the wrong lymphoma anyway. I have these two filed together and should not.",
     3, 71, ["Memory Failure"]),
    ("Leukemias & Lymphomas", "Chronic myeloid leukemia", "Chronic lymphocytic leukemia",
     "Smudge cells on the smear in an older adult with lymphocytosis. CML shows a left-shifted myeloid series instead.",
     "Rushed. I had eleven minutes for seven questions at that point.",
     2, 35, ["Time Pressure"]),
    ("Coagulation Disorders", "Hemophilia A", "von Willebrand disease",
     "Mucocutaneous bleeding with a prolonged bleeding time and a mildly raised PTT. Hemophilia gives deep joint and muscle bleeds.",
     "The bleeding pattern is the clue and I went straight to the lab values.",
     3, 77, ["Wrong Approach"]),
    ("Coagulation Disorders", "Disseminated intravascular coagulation", "Thrombotic thrombocytopenic purpura",
     "Normal PT and PTT. DIC consumes clotting factors and would prolong both.",
     "I let the schistocytes carry the whole answer without checking the coagulation studies.",
     4, 94, ["Incomplete Solution"]),
    ("Hypersensitivity Reactions", "Type II hypersensitivity", "Type III hypersensitivity",
     "Immune complex deposition with serum sickness after a drug. Type II is antibody directed against a fixed cell antigen.",
     "I can state the definitions and still cannot apply them under time. Needs examples, not definitions.",
     3, 86, ["Misunderstanding"]),
    ("Immunodeficiencies", "X-linked agammaglobulinemia", "Common variable immunodeficiency",
     "Onset in adulthood with normal B cell numbers. Bruton agammaglobulinemia presents in infancy with absent B cells.",
     "Age of onset again. That is the third time this week the age in the first sentence was the answer.",
     3, 69, ["Careless Mistake"]),
    ("Seizure Disorders", "Absence seizure", "Complex partial seizure",
     "There was postictal confusion and automatisms. Absence seizures have neither.",
     "I was anchored on the age of the patient and ignored the semiology.",
     3, 73, ["Wrong Approach"]),
    ("Cerebrovascular Disease", "Middle cerebral artery", "Lenticulostriate arteries",
     "A pure motor deficit without cortical signs is a lacunar infarct in the internal capsule.",
     "I knew that pure motor means lacunar and still picked the territory I think of first.",
     3, 81, ["Memory Failure"]),
    ("Cerebrovascular Disease", "Ischemic stroke", "Subarachnoid hemorrhage",
     "Thunderclap headache with nuchal rigidity and a normal CT does not exclude it; lumbar puncture is the next step.",
     "I second-guessed myself off the right answer because the CT was negative.",
     3, 92, ["Second-Guessing"]),
    ("Demyelinating Disease", "Guillain-Barre syndrome", "Multiple sclerosis",
     "Lesions separated in time and space with oligoclonal bands in the CSF.",
     "I read 'ascending weakness' into a stem that did not say it.",
     2, 57, ["Misread Question"]),
    ("Mood Disorders", "Major depressive disorder", "Bipolar II disorder",
     "There was a prior hypomanic episode in the history. One hypomanic episode changes the diagnosis and the treatment.",
     "I read the history as background rather than as part of the question.",
     3, 64, ["Misread Question"]),
    ("Neurodegenerative Disease", "Alzheimer disease", "Lewy body dementia",
     "Visual hallucinations and parkinsonism early in the course, with fluctuating cognition.",
     "I default to Alzheimer for any dementia stem. That default is costing me.",
     2, 59, ["Wrong Approach"]),
    ("Obstructive Lung Disease", "Asthma", "Chronic obstructive pulmonary disease",
     "The obstruction did not reverse after bronchodilator. Reversibility is the discriminator.",
     "The post-bronchodilator number was in the table and I only read the first column.",
     2, 50, ["Careless Mistake"]),
    ("Pulmonary Vascular Disease", "Pneumonia", "Pulmonary embolism",
     "Sudden pleuritic pain with hypoxia and a clear chest film, after a long flight.",
     "I let the fever pull me to an infectious answer and ignored everything else.",
     3, 76, ["Wrong Approach"]),
    ("Sepsis & Shock", "Cardiogenic shock", "Septic shock",
     "Warm extremities with a wide pulse pressure and low systemic vascular resistance.",
     "I had this right and changed it in the last thirty seconds.",
     3, 103, ["Second-Guessing"]),
    ("Fluid & Electrolyte Disorders", "Correct sodium rapidly", "Correct sodium no faster than 8 mEq/L per day",
     "Rapid correction of chronic hyponatremia causes osmotic demyelination.",
     "I knew the complication and not the number. The number is the answer.",
     2, 47, ["Knowledge Gap"]),
    ("Nutritional Deficiency", "Vitamin B1 deficiency", "Vitamin B3 deficiency",
     "Dermatitis, diarrhea and dementia is niacin. Thiamine gives the ophthalmoplegia and ataxia picture.",
     "Mixed up two vitamin mnemonics I have known for months.",
     2, 42, ["Memory Failure"]),
    ("Liver Disease", "Alcoholic hepatitis", "Non-alcoholic steatohepatitis",
     "AST to ALT ratio below 1 and no drinking history. Alcoholic hepatitis runs a ratio above 2.",
     "I did not compute the ratio, I just saw two raised transaminases.",
     2, 55, ["Incomplete Solution"]),
    ("Malabsorption", "Celiac disease", "Tropical sprue",
     "Travel history and a response to antibiotics. Celiac responds to diet, not antibiotics.",
     "Skipped the travel history entirely.",
     3, 67, ["Misread Question"]),
    ("Inflammatory Bowel Disease", "Ulcerative colitis", "Crohn disease",
     "Skip lesions with transmural inflammation and a fistula.",
     "I answered from the bloody diarrhea alone and ignored the biopsy.",
     2, 52, ["Careless Mistake"]),
    ("Inflammatory Arthritis", "Rheumatoid arthritis", "Psoriatic arthritis",
     "Distal interphalangeal involvement with nail pitting. Rheumatoid spares the DIP joints.",
     "I know rheumatoid spares the DIPs. Under time I did not check which joints were listed.",
     3, 74, ["Time Pressure"]),
    ("Muscle Disorders", "Polymyositis", "Dermatomyositis",
     "A heliotrope rash and Gottron papules. The skin findings are the whole difference.",
     "The rash was described in clinical language I did not translate fast enough.",
     2, 61, ["Knowledge Gap"]),
    ("Bullous Skin Disease", "Bullous pemphigoid", "Pemphigus vulgaris",
     "Oral involvement with a positive Nikolsky sign and intraepidermal splitting.",
     "I had the two split levels the wrong way round.",
     3, 70, ["Misunderstanding"]),
    ("Study Design", "Case-control study", "Cohort study",
     "Subjects were enrolled by exposure and followed forward for the outcome.",
     "I read 'retrospective' and jumped to case-control. A retrospective cohort is still a cohort.",
     3, 80, ["Misunderstanding"]),
    ("Diagnostic Testing", "Sensitivity 0.80", "Sensitivity 0.89",
     "True positives over true positives plus false negatives. I used the wrong denominator.",
     "I built the two-by-two table wrong under time pressure. Draw it every time, even when it feels slow.",
     3, 97, ["Calculation Error"]),
    ("Measures of Association", "Relative risk", "Odds ratio",
     "A case-control study cannot produce a relative risk because incidence is not measurable in it.",
     "I knew the rule and answered the arithmetic the question offered instead of asking whether it applied.",
     3, 85, ["Wrong Approach"]),
    ("Communication Skills", "Tell the family first", "Ask the patient what they want to know",
     "Patient autonomy governs disclosure, and the first step is always to establish what the patient wants.",
     "I picked the answer that felt kind rather than the one that follows the principle.",
     2, 45, ["Misunderstanding"]),
    ("Medical Ethics", "Obtain a court order", "Treat under implied consent",
     "An unconscious patient in an emergency with no surrogate available is treated under implied consent.",
     "I overthought a question that was testing one definition.",
     2, 38, ["Second-Guessing"]),
    ("Neoplasia", "Grade", "Stage",
     "Stage describes spread and is the stronger prognostic factor. Grade describes differentiation.",
     "I have confused these two before. Writing it down this time.",
     2, 43, ["Memory Failure"]),
    ("Cell Injury", "Apoptosis", "Coagulative necrosis",
     "Preserved tissue architecture after an ischemic insult, with loss of nuclei.",
     "I rushed the histology description.",
     3, 66, ["Careless Mistake"]),
    ("Cardiac Physiology", "Preload increases", "Afterload increases",
     "The pressure-volume loop shifted so that the aortic valve opened at a higher pressure.",
     "I cannot read these loops quickly enough yet and guessed.",
     4, 118, ["Knowledge Gap"]),
    ("Renal Physiology", "Decreased", "Increased",
     "Constricting the efferent arteriole raises glomerular capillary pressure and therefore GFR.",
     "I reasoned about renal blood flow and answered GFR. They move in opposite directions here.",
     4, 112, ["Misunderstanding"]),
    ("Respiratory Physiology", "Shift left", "Shift right",
     "Acidosis, raised temperature and raised 2,3-BPG all shift the curve right.",
     "I know the curve and reversed the direction under time.",
     2, 46, ["Careless Mistake"]),
    ("Autonomic Agents", "Beta-1 agonist", "Alpha-1 agonist",
     "Blood pressure rose with a reflex bradycardia. A beta-1 agonist would raise the heart rate.",
     "The reflex bradycardia is the discriminator and I did not use it.",
     3, 83, ["Wrong Approach"]),
    ("Antimicrobials", "Vancomycin", "Linezolid",
     "The organism was vancomycin-resistant Enterococcus.",
     "I read the sensitivities panel too quickly.",
     2, 49, ["Misread Question"]),
    ("Cardiovascular Drugs", "Amiodarone", "Adenosine",
     "A regular narrow-complex supraventricular tachycardia after vagal manoeuvres failed.",
     "Answered the chronic management rather than the acute step.",
     2, 53, ["Misread Question"]),
    ("Metabolism", "Glycogen storage disease type I", "Glycogen storage disease type V",
     "Exercise intolerance with a second wind and no hypoglycemia. McArdle disease is muscle only.",
     "I did not notice the glucose was normal.",
     3, 78, ["Incomplete Solution"]),
    ("Molecular Biology", "Nonsense mutation", "Frameshift mutation",
     "A single base insertion shifts the reading frame from that point on.",
     "Careless. I read 'insertion' and still answered nonsense.",
     2, 41, ["Careless Mistake"]),
    ("Vitamins", "Vitamin A toxicity", "Vitamin D toxicity",
     "Hypercalcemia with a raised phosphate after supplement use.",
     "Guessed between two I could not separate.",
     3, 72, ["Wrong Guess Strategy"]),
    ("Thorax & Abdomen", "Phrenic nerve", "Long thoracic nerve",
     "Winged scapula follows serratus anterior denervation.",
     "Straight recall failure after a short night.",
     2, 39, ["Fatigue Related"]),
    ("Head & Neck", "Facial nerve", "Trigeminal nerve",
     "Loss of sensation over the cheek without weakness is sensory, so trigeminal.",
     "I conflated the motor and sensory supply of the face.",
     2, 56, ["Misunderstanding"]),
    ("Bacteriology", "Staphylococcus aureus", "Staphylococcus epidermidis",
     "Coagulase negative and growing on a prosthetic valve.",
     "The coagulase result was the whole question and I skimmed it.",
     2, 44, ["Careless Mistake"]),
    ("Bacteriology", "Gram-positive rod", "Gram-negative diplococcus",
     "The Gram stain description was in the stem and I inverted it.",
     "This is the second inversion error today. I am reading too fast after question forty.",
     2, 37, ["Fatigue Related", "Careless Mistake"]),
    ("Virology", "Hepatitis B surface antigen", "Hepatitis B core IgM antibody",
     "The window period, when surface antigen has cleared and surface antibody has not yet appeared.",
     "I do not have the serology table solid. Writing it out rather than rereading it.",
     4, 105, ["Knowledge Gap"]),
    ("Mycology & Parasitology", "Candida albicans", "Aspergillus fumigatus",
     "Septate hyphae branching at acute angles, in a neutropenic patient.",
     "Knew the morphology, picked the wrong organism anyway.",
     3, 68, ["Memory Failure"]),
    ("Epithelia & Connective Tissue", "Type I collagen", "Type IV collagen",
     "Basement membrane collagen is type IV.",
     "Pure recall. These numbers need a drill rather than more reading.",
     2, 36, ["Memory Failure"]),
    ("Psychopathology", "Schizophrenia", "Schizophreniform disorder",
     "Symptoms had lasted two months. Schizophrenia requires six.",
     "The duration was in the first line.",
     2, 48, ["Misread Question"]),
    ("Substance Use", "Opioid withdrawal", "Alcohol withdrawal",
     "Tremor with autonomic hyperactivity and a seizure. Opioid withdrawal does not cause seizures.",
     "I let the agitation carry the answer.",
     3, 65, ["Wrong Approach"]),
    ("Adaptive Immunity", "IgM", "IgA",
     "Secretory immunoglobulin at mucosal surfaces is IgA.",
     "Answered the primary response reflex instead of reading 'mucosal'.",
     2, 40, ["Careless Mistake"]),
    ("Innate Immunity", "Classical pathway", "Alternative pathway",
     "Activation on a microbial surface with no antibody involved.",
     "I did not register that no antibody was mentioned.",
     3, 71, ["Incomplete Solution"]),
    ("Inheritance Patterns", "Autosomal recessive", "X-linked recessive",
     "Only males affected, with transmission through unaffected mothers.",
     "I read the pedigree too fast and missed that no father-to-son transmission occurred.",
     3, 88, ["Careless Mistake"]),
    ("Chromosomal Disorders", "Trisomy 21", "Trisomy 18",
     "Rocker-bottom feet with clenched hands and overlapping fingers.",
     "Guessed on the physical findings.",
     3, 74, ["Wrong Guess Strategy"]),
    ("Embryology", "Second pharyngeal arch", "Third pharyngeal arch",
     "The inferior parathyroids and the thymus come from the third pouch.",
     "Arches and pouches are still not separate in my head.",
     4, 99, ["Knowledge Gap"]),
    ("Valvular Disease", "Aortic stenosis", "Hypertrophic cardiomyopathy",
     "The murmur got louder with Valsalva. Aortic stenosis gets quieter.",
     "I know the manoeuvres and did not apply them.",
     3, 79, ["Wrong Approach"]),
    ("Inflammation & Repair", "Neutrophils", "Macrophages",
     "At three days the infiltrate has shifted to macrophages.",
     "I answered the first phase rather than reading the time point.",
     2, 50, ["Misread Question"]),
]

SESSIONS = [
    ("UWorld Block 1", 40, 36),
    ("UWorld Block 2", 40, 34),
    ("NBME Form 25", 50, 33),
    ("UWorld Block 3", 40, 31),
    ("UWorld Block 4", 40, 29),
    ("Free 120", 40, 24),
    ("UWorld Block 5", 40, 26),
    ("NBME Form 26", 50, 28),
]


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    app_data = Path(sys.argv[1]).resolve()
    app_data.mkdir(parents=True, exist_ok=True)

    rng = random.Random(20261004)

    master = MasterDatabase(app_data)
    user = master.create_user(username="demo", display_name="Demo")
    db_path = master.ensure_user_database(user.id)
    db = UserDatabase(
        db_path=db_path,
        user_id=user.id,
        username=user.username,
        device_id=master.get_device_id(),
    )

    db._ensure_phase2_schema()
    db._ensure_phase4_schema()

    exam = db.create_exam_context(
        exam_name=EXAM,
        exam_description="Step 1 preparation, six weeks in.",
        exam_date=date.today() + timedelta(days=54),
        hierarchy_levels=["System", "Topic"],
    )
    db.seed_default_tags(EXAM)
    tags = {t.tag_name: t.id for t in db.get_tags_by_exam(EXAM)}

    dims = {
        "Systems": db.create_dimension(
            exam_id=exam.id, name="Systems", display_order=1,
            description="Organ system the item is coded to"),
        "Disciplines": db.create_dimension(
            exam_id=exam.id, name="Disciplines", display_order=2,
            description="Basic science discipline the item draws on"),
    }

    topic_ids: dict[str, int] = {}

    def build(tree, dimension_id):
        for order, (name, low, high, children) in enumerate(tree, start=1):
            root = db.create_subject_node(
                exam_context=EXAM, name=name, level_type="System",
                dimension_id=dimension_id, sort_order=order,
                exam_weight_low=float(low), exam_weight_high=float(high),
                exam_source="official")
            # Share the parent's midpoint across its topics. Leaving the
            # topics unweighted makes every parent report "children's weights
            # leave room under this parent", so the tree editor draws an amber
            # feasibility triangle on all 21 roots. That is a true statement
            # about a half-filled tree and a false impression of the product.
            share = round(((low + high) / 2) / len(children), 1)
            for child_order, child in enumerate(children, start=1):
                node = db.create_subject_node(
                    exam_context=EXAM, name=child, level_type="Topic",
                    parent_id=root.id, dimension_id=dimension_id,
                    sort_order=child_order,
                    exam_weight_low=share, exam_weight_high=share)
                topic_ids[child] = node.id

    build(SYSTEMS, dims["Systems"])
    build(DISCIPLINES, dims["Disciplines"])

    # Spread the entries over eight sessions across six weeks, oldest first.
    start = date.today() - timedelta(days=41)
    per = [len(ENTRIES) // len(SESSIONS)] * len(SESSIONS)
    for i in range(len(ENTRIES) - sum(per)):
        per[i] += 1

    cursor = 0
    for index, ((name, total, wrong), count) in enumerate(zip(SESSIONS, per)):
        when = start + timedelta(days=index * 5 + rng.randint(0, 2))
        session = db.create_review_session(
            exam_context_id=exam.id, total_questions=total,
            total_incorrect=wrong, session_name=name, date_encountered=when,
            session_duration_minutes=rng.randint(55, 75))
        for topic, mine, right, why, reflection, difficulty, seconds, errs in \
                ENTRIES[cursor:cursor + count]:
            node_id = topic_ids.get(topic)
            db.create_question_entry(
                review_session_id=session.id,
                user_answer=mine,
                correct_answer=right,
                explanation=f"<p>{why}</p>",
                reflection=f"<p>{reflection}</p>",
                perceived_difficulty=difficulty,
                time_spent_seconds=seconds,
                primary_subject_ids=[node_id] if node_id else None,
                tag_ids=[tags[e] for e in errs if e in tags],
            )
        cursor += count

    # Close every session but the most recent one. create_question_entry does
    # not advance entries_completed, so without this the dashboard reads
    # "8 sessions, 0 completed", which describes the seeding rather than the
    # student. The newest stays open because that is the realistic state.
    with db.transaction():
        db.execute(
            "UPDATE review_sessions SET session_status = 'completed', "
            "entries_completed = total_incorrect, "
            "completed_at = CURRENT_TIMESTAMP "
            "WHERE id < (SELECT MAX(id) FROM review_sessions)")

    missing = sorted({e[0] for e in ENTRIES} - set(topic_ids))
    print(f"exam {exam.id}, user {user.id}, {len(ENTRIES)} entries, "
          f"{len(topic_ids)} topics, {len(SESSIONS)} sessions")
    if missing:
        print(f"WARNING: no subject node for {missing}")
    print(f"profile: {db_path}")
    db.close()
    master.close()
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main())
