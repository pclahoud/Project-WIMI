#!/usr/bin/env python3
"""Generator for ``tests/fixtures/exam_outline.json``.

**The committed fixture is a static file. This script produced it.** Tests read
``exam_outline.json``; nothing in the suite imports or runs this module. Re-run
it only when the fixture itself should change::

    python tests/fixtures/build_exam_outline.py          # rewrite the fixture
    python tests/fixtures/build_exam_outline.py --check  # fail if it is stale

Why a generator at all: the fixture carries 2,355 topic listings over 2,245
distinct names, under 21 roots and 205 categories, so that polyhierarchy
traversal and the folder-sync round trip are exercised at the scale a real
blueprint reaches. Hand-writing that many entries would make a review
impossible and a correction unrepeatable. The vocabulary below is hand-authored
real medical terminology; the *volume* comes from expanding it through a small
number of blueprint-shaped patterns ("anatomy of the <structure>", "adverse
effects of <agent>", "<organism> <syndrome>"), which is how a published content
outline is actually written. Seeded, that is 2,471 ``subject_nodes`` and 2,560
``subject_edges``, measured.

**Why this fixture exists rather than a published outline (#437).** It replaces
``usmle_step1_outline.txt``, which was a verbatim copy of NBME/FSMB's published
USMLE Content Outline -- their front matter, their prose and both registered
trademarks -- inside a repository whose own ``LICENSE`` declares the whole work
GPL-3.0. Facts and terminology are not the problem; a particular document's
selection, arrangement and wording are. So the terminology here is real and
deliberately so, while the structure, the category names, the ordering and the
selection are this project's own. Nothing is copied.

What the fixture has to be able to do, because something asserts it:

* **more than 2,000 subject nodes** once seeded -- ``tests/app/
  test_foldersync_roundtrip.py`` round-trips a realistically large profile;
* at least 50 topics with **two or more parents** (there are 70, every one of
  them declared in :data:`CROSS_LISTINGS` -- no accidental duplicates),
  including ``hypertension`` and ``deep venous thrombosis`` as single canonical
  nodes -- ``tests/wimi_test/test_seeders.py``;
* every speech-to-text priming term in ``stt_vocabulary_terms.json`` present
  **verbatim** -- ``tests/test_stt_measure.py``'s anti-oracle guard. That guard
  is what stops the priming prompt being built from the words being scored, so
  the terms are placed here by construction and :func:`_check_priming_terms`
  fails the build if one goes missing.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUTLINE_PATH = HERE / "exam_outline.json"
CORPUS_PATH = HERE / "stt_vocabulary_terms.json"

EXAM_NAME = "Synthetic Exam Outline (Test Fixture)"


# ---------------------------------------------------------------------------
# Expansion patterns
#
# Each is a shape a real content outline uses. They are what turns a compact
# list of real structures, agents and organisms into the several thousand
# entries a blueprint of this size has.
# ---------------------------------------------------------------------------

STRUCTURE_PATTERNS = (
    "anatomy of the {}",
    "histology of the {}",
    "normal physiology of the {}",
    "embryologic development of the {}",
)
AGENT_PATTERNS = (
    "mechanism of action of {}",
    "adverse effects of {}",
    "pharmacokinetics of {}",
)
STUDY_PATTERN = "interpretation of {}"

STRUCTURE_CATEGORY = "Normal structure and function"
AGENT_CATEGORY = "Pharmacology and therapeutics"
STUDY_CATEGORY = "Diagnostic studies and interpretation"
ORGANISM_CATEGORY = "Microbial causes"


# ---------------------------------------------------------------------------
# The vocabulary, one entry per root.
#
# Keys, all optional except ``name`` and ``conditions``:
#   structures  -> expanded through STRUCTURE_PATTERNS under STRUCTURE_CATEGORY
#   conditions  -> {category: [topic, ...]} or {category: {sub: [topic, ...]}}
#   organisms   -> [(syndrome, [organism, ...])] under ORGANISM_CATEGORY
#   agents      -> expanded through AGENT_PATTERNS under AGENT_CATEGORY
#   studies     -> expanded through STUDY_PATTERN under STUDY_CATEGORY
# ---------------------------------------------------------------------------

ROOTS: tuple[dict, ...] = (
    {
        "name": "Cardiovascular System",
        "structures": [
            "heart", "cardiac conduction system", "coronary arteries",
            "cardiac valves", "pericardium", "aorta", "systemic veins",
            "capillary bed",
        ],
        "conditions": {
            "Ischemic heart disease": [
                "acute coronary syndrome", "acute myocardial infarction",
                "angina pectoris", "coronary artery disease", "stable angina",
                "unstable angina", "coronary vasospasm",
                "silent myocardial ischemia",
                "post-infarction ventricular aneurysm",
            ],
            "Disorders of rhythm and conduction": [
                "atrial flutter", "atrial fibrillation",
                "multifocal atrial tachycardia", "ventricular tachycardia",
                "ventricular fibrillation", "torsades de pointes",
                "sick sinus syndrome", "Wolff-Parkinson-White syndrome",
                "atrioventricular block", "bundle branch block",
                "premature ventricular contractions",
                "congenital long QT syndrome",
            ],
            "Disorders of myocardial function": [
                "congestive heart failure", "cor pulmonale",
                "diastolic dysfunction", "systolic dysfunction",
                "cardiomyopathy", "dilated cardiomyopathy",
                "hypertrophic cardiomyopathy", "restrictive cardiomyopathy",
                "left ventricular hypertrophy", "cardiogenic shock",
            ],
            "Pericardial and valvular disorders": [
                "acute pericarditis", "pericardial effusion",
                "cardiac tamponade", "constrictive pericarditis",
                "rheumatic heart disease", "aortic stenosis",
                "aortic regurgitation", "mitral stenosis",
                "mitral regurgitation", "mitral valve prolapse",
                "tricuspid regurgitation", "bicuspid aortic valve",
            ],
            "Vascular disorders": [
                "atherosclerosis", "orthostatic hypotension",
                "essential hypertension", "hypertensive emergency",
                "secondary hypertension", "hypercholesterolemia",
                "hyperlipidemia", "hypertriglyceridemia", "claudication",
                "peripheral arterial disease", "thromboangiitis obliterans",
                "deep venous thrombosis", "venous thromboembolism",
                "thrombophlebitis", "venous insufficiency",
                "aortic dissection", "abdominal aortic aneurysm",
                "varicose veins", "Raynaud phenomenon",
                "giant cell arteritis",
            ],
            "Infectious and inflammatory disorders": [
                "bacterial endocarditis", "myocarditis", "rheumatic fever",
                "Kawasaki disease", "Takayasu arteritis",
                "polyarteritis nodosa",
            ],
            "Structural and congenital disorders": [
                "atrial septal defect", "ventricular septal defect",
                "patent ductus arteriosus", "coarctation of the aorta",
                "tetralogy of Fallot", "transposition of the great arteries",
                "Ebstein anomaly", "persistent truncus arteriosus",
            ],
        },
        "organisms": [
            ("infective endocarditis", [
                "Staphylococcus aureus", "Streptococcus sanguinis",
                "Enterococcus faecalis", "Candida albicans",
                "Coxiella burnetii",
            ]),
        ],
        "agents": [
            "warfarin", "furosemide", "spironolactone", "amiodarone",
            "ACE inhibitors", "digoxin", "metoprolol", "statins",
        ],
        "studies": [
            "the electrocardiogram", "the echocardiogram",
            "cardiac troponin levels", "coronary angiography",
            "the lipid panel", "the ankle-brachial index",
        ],
    },
    {
        "name": "Respiratory System",
        "structures": [
            "upper airway", "trachea and bronchi", "alveolus", "lung",
            "pleura", "diaphragm", "pulmonary vasculature",
            "respiratory control centre",
        ],
        "conditions": {
            "Obstructive disorders": [
                "asthma", "bronchiectasis",
                "chronic obstructive pulmonary disease", "chronic bronchitis",
                "emphysema", "bronchiolitis obliterans",
                "alpha-1 antitrypsin deficiency",
                "exercise-induced bronchoconstriction",
            ],
            "Restrictive and interstitial disorders": [
                "pneumoconiosis", "asbestosis", "silicosis",
                "hypersensitivity pneumonitis", "idiopathic pulmonary fibrosis",
                "sarcoidosis of the lung", "berylliosis",
                "coal workers pneumoconiosis", "radiation pneumonitis",
            ],
            "Disorders of gas exchange and ventilation": [
                "acute respiratory distress syndrome", "hypoventilation",
                "hypoxia", "hypercapnia", "respiratory acidosis",
                "respiratory alkalosis", "obstructive sleep apnea",
                "central sleep apnea", "high-altitude pulmonary edema",
            ],
            "Vascular disorders": [
                "pulmonary hypertension", "pulmonary edema",
                "pulmonary embolism", "pulmonary arteriovenous malformation",
                "pulmonary infarction",
            ],
            "Pleural and mediastinal disorders": [
                "pleural effusion", "pneumothorax", "tension pneumothorax",
                "empyema", "chylothorax", "mediastinitis",
                "pleural plaque formation",
            ],
            "Neoplastic disorders": [
                "small cell carcinoma of the lung",
                "squamous cell carcinoma of the lung",
                "adenocarcinoma of the lung",
                "large cell carcinoma of the lung", "bronchial carcinoid",
                "pulmonary hamartoma", "malignant pleural mesothelioma",
            ],
            "Structural and congenital disorders": [
                "tracheoesophageal fistula", "congenital diaphragmatic hernia",
                "pulmonary hypoplasia", "bronchogenic cyst",
                "primary ciliary dyskinesia",
            ],
        },
        "organisms": [
            ("pneumonia", [
                "Streptococcus pneumoniae", "Klebsiella pneumoniae",
                "Legionella pneumophila", "Mycoplasma pneumoniae",
                "Pneumocystis jirovecii", "Influenza A virus",
            ]),
            ("bronchiolitis", [
                "respiratory syncytial virus", "human metapneumovirus",
            ]),
        ],
        "agents": [
            "albuterol", "ipratropium", "montelukast",
            "inhaled corticosteroids", "theophylline", "roflumilast",
            "supplemental oxygen", "acetylcysteine",
        ],
        "studies": [
            "spirometry", "the flow-volume loop", "arterial blood gases",
            "the chest radiograph", "the ventilation-perfusion scan",
            "the methacholine challenge test",
        ],
    },
    {
        "name": "Gastrointestinal System",
        "structures": [
            "esophagus", "stomach", "small intestine", "colon", "rectum",
            "liver", "biliary tree", "exocrine pancreas", "peritoneum",
        ],
        "conditions": {
            "Disorders of the esophagus and stomach": [
                "peptic ulcer", "gastritis", "gastroparesis",
                "gastroesophageal reflux disease", "achalasia",
                "esophageal varices", "Barrett esophagus",
                "eosinophilic esophagitis", "Mallory-Weiss tear",
                "pyloric stenosis", "Zollinger-Ellison syndrome",
            ],
            "Disorders of the intestine": [
                "Crohn disease", "ulcerative colitis", "celiac disease",
                "irritable bowel syndrome", "diverticulitis",
                "ischemic colitis", "small intestinal bacterial overgrowth",
                "lactase deficiency", "intussusception", "volvulus",
                "adhesive small bowel obstruction", "acute appendicitis",
                "Hirschsprung disease", "necrotizing enterocolitis",
            ],
            "Hepatic and biliary disorders": [
                "cirrhosis", "primary sclerosing cholangitis",
                "primary biliary cholangitis", "autoimmune hepatitis",
                "nonalcoholic steatohepatitis", "alcoholic hepatitis",
                "hepatic encephalopathy", "portal hypertension",
                "cholelithiasis", "acute cholecystitis", "choledocholithiasis",
                "ascending cholangitis", "hereditary hemochromatosis",
                "Wilson disease", "Gilbert syndrome",
            ],
            "Pancreatic disorders": [
                "acute pancreatitis", "chronic pancreatitis",
                "pancreatic pseudocyst", "pancreatic insufficiency",
            ],
            "Neoplastic disorders": [
                "adenocarcinoma of the colon",
                "adenocarcinoma of the stomach",
                "adenocarcinoma of the pancreas",
                "squamous cell carcinoma of the esophagus",
                "hepatocellular carcinoma", "gastrointestinal stromal tumor",
                "familial adenomatous polyposis", "colonic adenoma",
            ],
        },
        "organisms": [
            ("infectious diarrhea", [
                "Salmonella enterica", "Shigella flexneri",
                "Campylobacter jejuni", "Clostridioides difficile",
                "Entamoeba histolytica", "norovirus", "rotavirus",
            ]),
            ("hepatitis", [
                "hepatitis A virus", "hepatitis B virus", "hepatitis C virus",
                "hepatitis E virus",
            ]),
        ],
        "agents": [
            "omeprazole", "ondansetron", "mesalamine", "lactulose",
            "ursodeoxycholic acid", "loperamide", "polyethylene glycol",
            "octreotide",
        ],
        "studies": [
            "liver function tests", "the serum lipase level",
            "upper endoscopy findings", "the abdominal radiograph",
            "the hepatitis serology panel", "the fecal occult blood test",
        ],
    },
    {
        "name": "Renal & Urinary System",
        "structures": [
            "kidney", "glomerulus", "proximal tubule", "loop of Henle",
            "distal nephron", "collecting duct", "ureter", "bladder",
            "urethra",
        ],
        "conditions": {
            "Glomerular disorders": [
                "glomerulonephritis", "IgA nephropathy", "lupus nephritis",
                "minimal change disease", "nephrotic syndrome",
                "membranous nephropathy",
                "focal segmental glomerulosclerosis",
                "post-streptococcal glomerulonephritis",
                "rapidly progressive glomerulonephritis",
                "diabetic nephropathy", "Alport syndrome",
                "thin basement membrane disease",
            ],
            "Tubulointerstitial disorders": [
                "acute tubular necrosis", "acute interstitial nephritis",
                "chronic interstitial nephritis", "renal papillary necrosis",
                "Fanconi syndrome", "renal tubular acidosis",
                "nephrogenic diabetes insipidus",
                "analgesic nephropathy",
            ],
            "Infectious and inflammatory disorders": [
                "pyelonephritis", "cystitis", "urethritis", "prostatitis",
                "perinephric abscess", "emphysematous pyelonephritis",
            ],
            "Obstructive and structural disorders": [
                "nephrolithiasis", "hydronephrosis",
                "polycystic kidney disease", "horseshoe kidney",
                "vesicoureteral reflux", "posterior urethral valves",
                "neurogenic bladder", "urinary retention",
            ],
            "Vascular and hypertensive disorders": [
                "renal artery stenosis", "hypertensive nephrosclerosis",
                "renal vein thrombosis", "renal infarction",
                "scleroderma renal crisis",
            ],
            "Disorders of fluid and electrolytes": [
                "hyponatremia", "hypernatremia", "hyperkalemia",
                "hypokalemia", "metabolic acidosis", "metabolic alkalosis",
                "hypercalcemia of malignancy", "volume depletion",
            ],
            "Neoplastic disorders": [
                "renal cell carcinoma", "urothelial carcinoma of the bladder",
                "nephroblastoma", "angiomyolipoma of the kidney",
            ],
        },
        "organisms": [
            ("urinary tract infection", [
                "Escherichia coli", "Proteus mirabilis",
                "Klebsiella pneumoniae", "Enterococcus faecalis",
                "Staphylococcus saprophyticus",
            ]),
        ],
        "agents": [
            "hydrochlorothiazide", "acetazolamide", "tolvaptan",
            "sodium bicarbonate", "sevelamer", "erythropoietin",
            "nitrofurantoin", "allopurinol",
        ],
        "studies": [
            "the serum creatinine level", "urinalysis", "the urine sediment",
            "the fractional excretion of sodium", "renal ultrasonography",
            "the renal biopsy specimen",
        ],
    },
    {
        "name": "Endocrine System",
        "structures": [
            "pituitary gland", "thyroid gland", "parathyroid gland",
            "adrenal cortex", "adrenal medulla", "endocrine pancreas",
            "hypothalamic-pituitary axis", "bone mineral axis",
        ],
        "conditions": {
            "Disorders of glucose regulation": [
                "diabetes mellitus", "hypoglycemia",
                "diabetic ketoacidosis",
                "hyperosmolar hyperglycemic state", "insulin resistance",
                "gestational glucose intolerance", "insulinoma",
                "reactive hypoglycemia",
            ],
            "Disorders of the thyroid gland": [
                "Graves disease", "Hashimoto thyroiditis",
                "subacute thyroiditis", "toxic multinodular goiter",
                "iodine deficiency goiter", "thyroid storm",
                "myxedema coma", "papillary thyroid carcinoma",
                "medullary thyroid carcinoma", "congenital hypothyroidism",
            ],
            "Disorders of the adrenal gland": [
                "pheochromocytoma", "primary adrenal insufficiency",
                "secondary adrenal insufficiency", "Cushing syndrome",
                "primary hyperaldosteronism",
                "congenital adrenal hyperplasia", "adrenal incidentaloma",
                "adrenocortical carcinoma",
            ],
            "Disorders of the pituitary gland": [
                "prolactinoma", "acromegaly", "growth hormone deficiency",
                "central diabetes insipidus",
                "syndrome of inappropriate antidiuretic hormone secretion",
                "hypopituitarism", "pituitary apoplexy",
                "empty sella syndrome",
            ],
            "Disorders of calcium and bone metabolism": [
                "primary hyperparathyroidism", "hypoparathyroidism",
                "vitamin D deficiency rickets", "osteomalacia",
                "Paget disease of bone", "pseudohypoparathyroidism",
                "familial hypocalciuric hypercalcemia",
            ],
            "Multiple endocrine disorders": [
                "multiple endocrine neoplasia type 1",
                "multiple endocrine neoplasia type 2A",
                "autoimmune polyglandular syndrome",
                "carcinoid syndrome",
            ],
        },
        "agents": [
            "insulin", "metformin", "levothyroxine", "methimazole",
            "prednisone", "bisphosphonates", "cabergoline",
            "desmopressin",
        ],
        "studies": [
            "the thyroid-stimulating hormone level",
            "the hemoglobin A1c level", "the dexamethasone suppression test",
            "the cosyntropin stimulation test",
            "the oral glucose tolerance test", "bone densitometry",
        ],
    },
    {
        "name": "Nervous System & Special Senses",
        "structures": [
            "cerebral cortex", "basal ganglia", "cerebellum", "brainstem",
            "spinal cord", "peripheral nerve", "neuromuscular junction",
            "meninges", "retina", "cochlea",
        ],
        "conditions": {
            "Cerebrovascular disorders": [
                "ischemic stroke", "transient ischemic attack",
                "intracerebral hemorrhage", "subarachnoid hemorrhage",
                "cerebral venous sinus thrombosis", "lacunar infarction",
                "carotid artery stenosis", "cerebral aneurysm",
                "arteriovenous malformation of the brain",
            ],
            "Seizure and paroxysmal disorders": [
                "focal seizure", "generalized tonic-clonic seizure",
                "absence seizure", "status epilepticus", "febrile seizure",
                "juvenile myoclonic epilepsy", "syncope of neural origin",
            ],
            "Degenerative and demyelinating disorders": [
                "Alzheimer disease", "Parkinson disease",
                "Huntington disease", "amyotrophic lateral sclerosis",
                "multiple sclerosis", "frontotemporal dementia",
                "Lewy body dementia", "progressive supranuclear palsy",
                "normal pressure hydrocephalus",
                "subacute combined degeneration",
            ],
            "Disorders of the peripheral nerve and muscle": [
                "Guillain-Barre syndrome", "myasthenia gravis",
                "diabetic polyneuropathy", "carpal tunnel syndrome",
                "Bell palsy", "trigeminal neuralgia",
                "Charcot-Marie-Tooth disease",
                "Lambert-Eaton myasthenic syndrome",
            ],
            "Headache and pain disorders": [
                "migraine without aura", "migraine with aura",
                "cluster headache", "tension-type headache",
                "idiopathic intracranial hypertension",
                "medication overuse headache", "complex regional pain syndrome",
            ],
            "Disorders of the special senses": [
                "open-angle glaucoma", "angle-closure glaucoma",
                "age-related macular degeneration", "diabetic retinopathy",
                "retinal detachment", "cataract", "optic neuritis",
                "conductive hearing loss", "sensorineural hearing loss",
                "benign paroxysmal positional vertigo", "Meniere disease",
                "acute otitis media", "vestibular neuritis",
            ],
            "Neoplastic disorders": [
                "glioblastoma", "meningioma", "medulloblastoma",
                "vestibular schwannoma", "pituitary macroadenoma",
                "metastatic brain lesion",
            ],
            "Traumatic and mechanical disorders": [
                "concussion", "epidural hematoma", "subdural hematoma",
                "diffuse axonal injury", "spinal cord compression",
                "cauda equina syndrome", "lumbar disc herniation",
            ],
        },
        "organisms": [
            ("meningitis", [
                "Neisseria meningitidis", "Streptococcus pneumoniae",
                "Haemophilus influenzae", "Listeria monocytogenes",
                "Cryptococcus neoformans", "enterovirus",
            ]),
            ("encephalitis", [
                "herpes simplex virus type 1", "West Nile virus",
                "rabies virus",
            ]),
        ],
        "agents": [
            "levetiracetam", "phenytoin", "carbidopa-levodopa", "sumatriptan",
            "donepezil", "mannitol", "alteplase", "gabapentin",
        ],
        "studies": [
            "the non-contrast head computed tomogram",
            "magnetic resonance imaging of the brain",
            "the cerebrospinal fluid profile", "electroencephalography",
            "nerve conduction studies", "the audiogram",
        ],
    },
    {
        "name": "Musculoskeletal System",
        "structures": [
            "long bone", "synovial joint", "skeletal muscle", "tendon",
            "ligament", "intervertebral disc", "growth plate",
            "articular cartilage",
        ],
        "conditions": {
            "Inflammatory and autoimmune arthropathies": [
                "rheumatoid arthritis", "ankylosing spondylitis",
                "psoriatic arthropathy", "reactive arthritis",
                "juvenile idiopathic arthritis", "gout",
                "calcium pyrophosphate deposition disease",
                "polymyalgia rheumatica", "enteropathic arthritis",
            ],
            "Degenerative and metabolic bone disease": [
                "osteoarthritis", "osteoporosis", "osteopenia",
                "avascular necrosis of the femoral head",
                "osteogenesis imperfecta", "osteopetrosis",
                "fibrous dysplasia of bone",
            ],
            "Infectious disorders": [
                "osteomyelitis", "septic arthritis", "discitis",
                "prosthetic joint infection", "pyomyositis",
            ],
            "Disorders of muscle": [
                "rhabdomyolysis", "malignant hyperthermia",
                "polymyositis", "dermatomyositis", "inclusion body myositis",
                "Duchenne muscular dystrophy", "myotonic dystrophy",
                "statin-associated myopathy",
            ],
            "Traumatic and mechanical disorders": [
                "spondylolisthesis", "lumbar spinal stenosis",
                "rotator cuff tear", "anterior cruciate ligament tear",
                "meniscal tear", "Colles fracture", "scaphoid fracture",
                "femoral neck fracture", "compartment syndrome",
                "stress fracture of the tibia", "lateral epicondylitis",
                "plantar fasciitis", "adhesive capsulitis",
            ],
            "Neoplastic disorders": [
                "osteosarcoma", "Ewing sarcoma", "chondrosarcoma",
                "giant cell tumor of bone", "osteochondroma",
                "metastatic bone lesion",
            ],
            "Structural and congenital disorders": [
                "developmental dysplasia of the hip", "clubfoot",
                "adolescent idiopathic scoliosis", "achondroplasia",
                "Legg-Calve-Perthes disease",
            ],
        },
        "organisms": [
            ("osteoarticular infection", [
                "Staphylococcus aureus", "Neisseria gonorrhoeae",
                "Salmonella enterica", "Mycobacterium tuberculosis",
                "Kingella kingae",
            ]),
        ],
        "agents": [
            "colchicine", "methotrexate", "naproxen", "denosumab",
            "allopurinol for gout", "cyclobenzaprine", "triamcinolone",
            "etanercept",
        ],
        "studies": [
            "the plain radiograph of a fracture", "the synovial fluid analysis",
            "the serum creatine kinase level",
            "the rheumatoid factor assay",
            "the anti-citrullinated peptide antibody assay",
            "the serum uric acid level",
        ],
    },
    {
        "name": "Skin & Subcutaneous Tissue",
        "structures": [
            "epidermis", "dermis", "subcutaneous fat", "hair follicle",
            "sebaceous gland", "eccrine sweat gland", "nail unit",
            "cutaneous vasculature",
        ],
        "conditions": {
            "Infectious disorders": [
                "necrotizing fasciitis", "cellulitis", "erysipelas",
                "impetigo", "folliculitis", "cutaneous abscess",
                "tinea corporis", "onychomycosis", "herpes zoster",
                "scabies infestation", "verruca vulgaris",
            ],
            "Papulosquamous and eczematous disorders": [
                "plaque psoriasis", "atopic dermatitis",
                "allergic contact dermatitis", "irritant contact dermatitis",
                "seborrheic dermatitis", "lichen planus", "pityriasis rosea",
                "nummular eczema",
            ],
            "Bullous and immune-mediated disorders": [
                "pemphigus vulgaris", "bullous pemphigoid",
                "dermatitis herpetiformis", "erythema multiforme",
                "Stevens-Johnson syndrome", "toxic epidermal necrolysis",
                "cutaneous lupus erythematosus", "vitiligo",
            ],
            "Disorders of the appendages": [
                "acne vulgaris", "rosacea", "hidradenitis suppurativa",
                "androgenetic alopecia", "alopecia areata",
                "telogen effluvium", "hirsutism",
            ],
            "Neoplastic disorders": [
                "basal cell carcinoma", "cutaneous squamous cell carcinoma",
                "melanoma", "actinic keratosis", "seborrheic keratosis",
                "dysplastic nevus", "dermatofibroma", "keratoacanthoma",
                "mycosis fungoides",
            ],
            "Traumatic and mechanical disorders": [
                "pressure injury", "thermal burn", "chemical burn",
                "frostbite", "hypertrophic scar", "keloid formation",
            ],
        },
        "organisms": [
            ("skin and soft tissue infection", [
                "Staphylococcus aureus", "Streptococcus pyogenes",
                "Pseudomonas aeruginosa", "Clostridium perfringens",
                "Trichophyton rubrum",
            ]),
        ],
        "agents": [
            "topical clobetasol", "topical tacrolimus", "isotretinoin",
            "terbinafine", "mupirocin", "permethrin", "dupilumab",
            "acyclovir",
        ],
        "studies": [
            "the punch biopsy specimen", "the potassium hydroxide preparation",
            "dermoscopy findings", "patch testing",
            "the Tzanck smear", "wound culture results",
        ],
    },
    {
        "name": "Blood & Lymphoreticular System",
        "structures": [
            "bone marrow", "erythrocyte", "platelet", "neutrophil",
            "lymph node", "spleen", "coagulation cascade",
            "hemoglobin molecule",
        ],
        "conditions": {
            "Disorders of the erythrocyte": [
                "iron deficiency anemia", "anemia of chronic disease",
                "megaloblastic anemia", "sickle cell disease",
                "beta thalassemia", "alpha thalassemia",
                "hereditary spherocytosis",
                "glucose-6-phosphate dehydrogenase deficiency",
                "autoimmune hemolytic anemia", "aplastic anemia",
                "methemoglobinemia", "polycythemia vera",
                "paroxysmal nocturnal hemoglobinuria",
            ],
            "Disorders of platelets and coagulation": [
                "thrombocytopenia", "immune thrombocytopenic purpura",
                "heparin-induced thrombocytopenia",
                "thrombotic thrombocytopenic purpura",
                "disseminated intravascular coagulation", "hemophilia A",
                "hemophilia B", "von Willebrand disease",
                "factor V Leiden thrombophilia",
                "antithrombin III deficiency", "vitamin K deficiency bleeding",
                "essential thrombocythemia",
            ],
            "Disorders of leukocytes": [
                "acute lymphoblastic leukemia", "acute myeloid leukemia",
                "chronic lymphocytic leukemia", "chronic myeloid leukemia",
                "myelodysplastic syndrome", "hairy cell leukemia",
                "leukocyte adhesion deficiency", "chronic neutropenia",
            ],
            "Disorders of the lymphoreticular system": [
                "hypersplenism", "Hodgkin lymphoma",
                "diffuse large B-cell lymphoma", "follicular lymphoma",
                "Burkitt lymphoma", "multiple myeloma",
                "monoclonal gammopathy of undetermined significance",
                "reactive lymphadenopathy", "splenic infarction",
                "asplenia",
            ],
            "Transfusion and marrow failure": [
                "acute hemolytic transfusion reaction",
                "febrile non-hemolytic transfusion reaction",
                "transfusion-related acute lung injury",
                "graft-versus-host disease", "marrow engraftment failure",
                "iron overload from transfusion",
            ],
        },
        "agents": [
            "ferrous sulfate", "cyanocobalamin", "folic acid",
            "hydroxyurea", "rituximab", "azathioprine",
            "filgrastim", "eltrombopag",
        ],
        "studies": [
            "the complete blood count", "the peripheral blood smear",
            "the reticulocyte count", "the bone marrow aspirate",
            "the direct antiglobulin test",
            "the prothrombin and partial thromboplastin times",
        ],
    },
    {
        "name": "Immune System",
        "structures": [
            "thymus", "B lymphocyte", "T lymphocyte", "macrophage",
            "complement system", "major histocompatibility complex",
            "immunoglobulin molecule", "innate barrier defenses",
        ],
        "conditions": {
            "Immunodeficiency": [
                "severe combined immunodeficiency",
                "common variable immunodeficiency",
                "selective immunoglobulin A deficiency",
                "X-linked agammaglobulinemia",
                "chronic granulomatous disease", "DiGeorge syndrome",
                "hereditary complement deficiency",
                "acquired immunodeficiency syndrome",
                "hyper-immunoglobulin E syndrome",
            ],
            "Immunologic and allergic disorders": [
                "asthma", "allergic rhinitis", "anaphylaxis",
                "urticaria and angioedema", "food allergy",
                "drug hypersensitivity reaction", "serum sickness",
                "hereditary angioedema", "mast cell activation syndrome",
            ],
            "Autoimmune disorders": [
                "systemic lupus erythematosus", "Sjogren syndrome",
                "systemic sclerosis", "mixed connective tissue disease",
                "antiphospholipid antibody syndrome",
                "granulomatosis with polyangiitis",
                "eosinophilic granulomatosis with polyangiitis",
                "microscopic polyangiitis", "IgG4-related disease",
            ],
            "Transplantation and tolerance": [
                "hyperacute graft rejection", "acute cellular rejection",
                "chronic allograft nephropathy", "donor-recipient matching",
                "central tolerance", "peripheral tolerance",
            ],
            "Inflammation": [
                "the acute phase response", "granuloma formation",
                "chronic inflammatory infiltrate", "fever of inflammatory origin",
                "cytokine release syndrome", "sepsis",
            ],
        },
        "agents": [
            "epinephrine for anaphylaxis", "cetirizine", "omalizumab",
            "tacrolimus", "mycophenolate mofetil", "cyclosporine",
            "intravenous immunoglobulin", "infliximab",
        ],
        "studies": [
            "the antinuclear antibody panel",
            "serum immunoglobulin quantitation", "the complement levels",
            "flow cytometry of lymphocyte subsets", "skin prick testing",
            "the erythrocyte sedimentation rate",
        ],
    },
    {
        "name": "Microbiology & Infectious Disease",
        "structures": [
            "bacterial cell wall", "bacterial ribosome", "viral capsid",
            "fungal cell membrane", "protozoan life cycle",
            "helminth life cycle",
        ],
        "conditions": {
            "Bacterial infections": {
                "Gram-positive organisms": [
                    "MRSA colonization",
                    "methicillin-resistant Staphylococcus aureus bacteremia",
                    "streptococcal pharyngitis", "scarlet fever",
                    "toxic shock syndrome", "diphtheria",
                    "listeriosis", "anthrax", "tetanus", "botulism",
                    "nocardiosis", "actinomycosis",
                ],
                "Gram-negative organisms": [
                    "typhoid fever", "cholera", "plague", "tularemia",
                    "brucellosis", "pertussis", "legionellosis",
                    "melioidosis", "chancroid", "bartonellosis",
                ],
                "Mycobacterial and spirochetal organisms": [
                    "pulmonary tuberculosis", "miliary tuberculosis",
                    "leprosy", "Mycobacterium avium complex infection",
                    "primary syphilis", "secondary syphilis",
                    "tertiary syphilis", "Lyme disease", "leptospirosis",
                    "relapsing fever",
                ],
            },
            "Viral infections": [
                "infectious mononucleosis", "cytomegalovirus syndrome",
                "measles", "mumps", "rubella", "varicella",
                "herpes labialis", "genital herpes", "mpox",
                "dengue fever", "chikungunya fever", "Zika virus infection",
                "yellow fever", "poliomyelitis", "viral gastroenteritis",
                "human immunodeficiency virus infection",
            ],
            "Fungal infections": [
                "candidemia", "invasive aspergillosis", "mucormycosis",
                "histoplasmosis", "coccidioidomycosis", "blastomycosis",
                "cryptococcosis", "sporotrichosis",
            ],
            "Parasitic infections": [
                "malaria", "toxoplasmosis", "giardiasis",
                "cryptosporidiosis", "Chagas disease",
                "visceral leishmaniasis", "schistosomiasis",
                "strongyloidiasis", "echinococcosis", "neurocysticercosis",
                "ascariasis", "trichinellosis",
            ],
            "Antimicrobial resistance": [
                "extended-spectrum beta-lactamase production",
                "carbapenemase production",
                "vancomycin-resistant Enterococcus infection",
                "efflux-pump mediated resistance",
                "target-site mutation resistance",
                "antimicrobial stewardship principles",
            ],
            "Health care associated infection": [
                "catheter-associated urinary tract infection",
                "central line-associated bloodstream infection",
                "ventilator-associated pneumonia",
                "surgical site infection",
                "Clostridioides difficile colitis",
                "hand hygiene and transmission interruption",
            ],
        },
        "agents": [
            "penicillin", "ceftriaxone", "vancomycin", "azithromycin",
            "ciprofloxacin", "doxycycline", "metronidazole", "fluconazole",
            "isoniazid", "rifampin", "oseltamivir", "trimethoprim-sulfamethoxazole",
        ],
        "studies": [
            "the Gram stain", "blood culture results",
            "antimicrobial susceptibility testing",
            "the acid-fast stain", "nucleic acid amplification testing",
            "the interferon-gamma release assay",
        ],
    },
    {
        "name": "Multisystem Processes & Disorders",
        "structures": [
            "extracellular fluid compartment", "thermoregulatory system",
            "systemic inflammatory response", "oxygen delivery pathway",
            "acid-base buffering system", "nutritional reserve",
        ],
        "conditions": {
            "Shock and critical illness": [
                "sepsis", "bacteremia", "septic shock", "hypovolemic shock",
                "neurogenic shock", "anaphylactic shock",
                "obstructive shock", "multiple organ dysfunction syndrome",
                "systemic inflammatory response syndrome",
            ],
            "Nutritional and metabolic disorders": [
                "protein-energy malnutrition", "obesity",
                "metabolic syndrome", "vitamin A deficiency",
                "thiamine deficiency", "niacin deficiency",
                "vitamin C deficiency", "zinc deficiency",
                "refeeding syndrome", "iodine excess",
            ],
            "Oncologic emergencies and paraneoplastic processes": [
                "tumor lysis syndrome", "superior vena cava syndrome",
                "malignant spinal cord compression",
                "paraneoplastic cerebellar degeneration",
                "ectopic adrenocorticotropic hormone syndrome",
                "cancer-associated hypercoagulability",
                "febrile neutropenia",
            ],
            "Environmental and occupational injury": [
                "heat stroke", "hypothermia", "carbon monoxide poisoning",
                "lead poisoning", "organophosphate poisoning",
                "acetaminophen overdose", "salicylate overdose",
                "opioid overdose", "decompression sickness",
                "high-altitude cerebral edema", "electrical injury",
                "near-drowning",
            ],
            "Aging and frailty": [
                "frailty syndrome", "polypharmacy",
                "falls in the older adult", "pressure injury risk",
                "delirium in the hospitalized patient",
                "functional decline after hospitalization",
            ],
            "Fever and systemic presentations": [
                "fever of unknown origin", "unintentional weight loss",
                "generalized fatigue", "night sweats",
                "generalized lymphadenopathy", "failure to thrive",
            ],
        },
        "agents": [
            "norepinephrine", "intravenous crystalloid resuscitation",
            "activated charcoal", "naloxone", "acetylcysteine for overdose",
            "deferoxamine", "sodium thiosulfate", "thiamine repletion",
        ],
        "studies": [
            "the serum lactate level", "the anion gap",
            "the serum osmolal gap", "the toxicology screen",
            "the sepsis bundle timing", "the nutritional assessment",
        ],
    },
    {
        "name": "Pregnancy and the Puerperium",
        "structures": [
            "placenta", "umbilical cord", "amniotic cavity", "gravid uterus",
            "fetal circulation", "maternal plasma volume",
        ],
        "conditions": {
            "Antepartum complications": [
                "preeclampsia", "eclampsia", "HELLP syndrome",
                "gestational diabetes mellitus", "placenta previa",
                "placental abruption", "placenta accreta spectrum",
                "intrauterine growth restriction", "polyhydramnios",
                "oligohydramnios", "cervical insufficiency",
                "preterm premature rupture of membranes",
                "hyperemesis gravidarum", "Rh alloimmunization",
            ],
            "Medical disorders complicating pregnancy": [
                "chronic hypertension in pregnancy",
                "pregestational diabetes mellitus",
                "thyroid disease in pregnancy",
                "epilepsy in pregnancy",
                "venous thromboembolism in pregnancy",
                "intrahepatic cholestasis of pregnancy",
                "peripartum cardiomyopathy",
                "anemia of pregnancy",
            ],
            "Labour and delivery": [
                "preterm labour", "prolonged latent phase",
                "arrest of descent", "shoulder dystocia",
                "umbilical cord prolapse", "chorioamnionitis",
                "uterine rupture", "operative vaginal delivery",
                "caesarean delivery indications",
                "non-reassuring fetal heart tracing",
            ],
            "Postpartum disorders": [
                "postpartum hemorrhage", "uterine atony",
                "retained placental tissue", "endometritis",
                "postpartum depression", "mastitis",
                "lactation failure", "postpartum thyroiditis",
            ],
            "Early pregnancy loss and ectopic gestation": [
                "spontaneous abortion", "recurrent pregnancy loss",
                "ectopic pregnancy", "gestational trophoblastic disease",
                "hydatidiform mole", "septic abortion",
            ],
        },
        "agents": [
            "magnesium sulfate", "oxytocin", "betamethasone for fetal lungs",
            "labetalol in pregnancy", "folic acid supplementation",
            "anti-D immune globulin", "nifedipine tocolysis",
            "misoprostol",
        ],
        "studies": [
            "the obstetric ultrasound", "the nonstress test",
            "the biophysical profile", "the quadruple screen",
            "cell-free fetal DNA testing", "the glucose challenge test",
        ],
    },
    {
        "name": "Female Reproductive System",
        "structures": [
            "ovary", "uterus", "fallopian tube", "cervix", "vagina",
            "breast", "pelvic floor",
        ],
        "conditions": {
            "Disorders of the menstrual cycle": [
                "polycystic ovary syndrome", "primary amenorrhea",
                "secondary amenorrhea", "abnormal uterine bleeding",
                "premenstrual dysphoric disorder", "primary dysmenorrhea",
                "anovulatory infertility", "luteal phase deficiency",
            ],
            "Infectious and inflammatory disorders": [
                "pelvic inflammatory disease", "bacterial vaginosis",
                "vulvovaginal candidiasis", "trichomoniasis",
                "tubo-ovarian abscess", "cervicitis",
                "genital human papillomavirus infection",
            ],
            "Structural and benign neoplastic disorders": [
                "uterine leiomyoma", "endometriosis", "adenomyosis",
                "ovarian cyst", "ovarian torsion",
                "pelvic organ prolapse", "Bartholin gland cyst",
                "fibroadenoma of the breast",
            ],
            "Malignant neoplasms": [
                "endometrial carcinoma", "cervical carcinoma",
                "epithelial ovarian carcinoma", "vulvar carcinoma",
                "invasive ductal carcinoma of the breast",
                "ductal carcinoma in situ",
                "inflammatory breast carcinoma",
            ],
            "Menopause and the climacteric": [
                "vasomotor symptoms of menopause",
                "genitourinary syndrome of menopause",
                "premature ovarian insufficiency",
                "postmenopausal bleeding",
                "postmenopausal bone loss",
            ],
            "Contraception and fertility": [
                "combined hormonal contraception",
                "progestin-only contraception",
                "intrauterine device placement",
                "emergency contraception",
                "tubal factor infertility", "ovulation induction",
            ],
        },
        "agents": [
            "ethinyl estradiol", "levonorgestrel", "clomiphene citrate",
            "leuprolide", "tranexamic acid", "tamoxifen",
            "topical estrogen", "letrozole for ovulation",
        ],
        "studies": [
            "the pelvic ultrasound", "the cervical cytology smear",
            "the endometrial biopsy specimen",
            "screening mammography", "the day-3 follicle stimulating hormone level",
            "the hysterosalpingogram",
        ],
    },
    {
        "name": "Male Reproductive System",
        "structures": [
            "testis", "epididymis", "prostate gland", "seminal vesicle",
            "penis", "spermatic cord",
        ],
        "conditions": {
            "Infectious and inflammatory disorders": [
                "acute bacterial prostatitis", "chronic prostatitis",
                "epididymitis", "orchitis", "balanitis", "urethritis in men",
            ],
            "Structural and vascular disorders": [
                "testicular torsion", "varicocele", "hydrocele",
                "spermatocele", "inguinal hernia", "phimosis",
                "Peyronie disease", "priapism",
            ],
            "Neoplastic disorders": [
                "benign prostatic hyperplasia",
                "adenocarcinoma of the prostate", "seminoma",
                "non-seminomatous germ cell tumor",
                "penile squamous cell carcinoma", "Leydig cell tumor",
            ],
            "Disorders of function and fertility": [
                "erectile dysfunction", "premature ejaculation",
                "male hypogonadism", "azoospermia", "oligospermia",
                "retrograde ejaculation", "anabolic steroid use",
            ],
            "Developmental disorders": [
                "cryptorchidism", "hypospadias",
                "congenital absence of the vas deferens",
                "Klinefelter syndrome", "androgen insensitivity syndrome",
            ],
        },
        "agents": [
            "tamsulosin", "finasteride", "sildenafil",
            "testosterone replacement", "bicalutamide",
            "leuprolide for prostate cancer", "cabergoline for hyperprolactinemia",
            "human chorionic gonadotropin",
        ],
        "studies": [
            "the prostate-specific antigen level", "the semen analysis",
            "scrotal ultrasonography", "the serum testosterone level",
            "the prostate biopsy specimen", "the post-void residual volume",
        ],
    },
    {
        "name": "Human Development",
        "conditions": {
            "Prenatal and neonatal development": [
                "gametogenesis", "fertilization and implantation",
                "gastrulation", "neural tube closure",
                "organogenesis of the first trimester",
                "fetal lung maturation", "the Apgar assessment",
                "neonatal thermoregulation",
                "transition of the fetal circulation",
                "neonatal hyperbilirubinemia",
                "neonatal respiratory distress syndrome",
                "neonatal hypoglycemia",
            ],
            "Infancy and early childhood": [
                "infant gross motor milestones",
                "infant fine motor milestones",
                "infant language milestones",
                "attachment and separation behaviour",
                "introduction of complementary feeding",
                "primary tooth eruption", "toilet training readiness",
                "stranger anxiety",
            ],
            "School age and adolescence": [
                "concrete operational reasoning", "peer group formation",
                "pubertal staging", "adolescent growth spurt",
                "adolescent risk behaviour", "identity formation",
                "secondary sexual characteristic development",
                "menarche and spermarche",
            ],
            "Adulthood and aging": [
                "young adult role consolidation",
                "midlife reappraisal", "age-related sarcopenia",
                "age-related sensory decline",
                "normal age-related memory change",
                "retirement transition", "bereavement and grief",
                "end-of-life decision making",
            ],
            "Disorders of development": [
                "global developmental delay",
                "autism spectrum disorder",
                "attention-deficit hyperactivity disorder",
                "specific learning disorder",
                "developmental language disorder",
                "cerebral palsy", "intellectual disability",
                "fetal alcohol spectrum disorder",
                "constitutional growth delay",
                "precocious puberty", "delayed puberty",
                "failure to thrive in infancy",
            ],
            "Screening and preventive care across the lifespan": [
                "newborn metabolic screening",
                "childhood immunization schedule",
                "adolescent confidentiality in care",
                "adult cancer screening intervals",
                "fall risk screening in older adults",
                "cognitive screening in older adults",
            ],
        },
        "studies": [
            "the growth chart", "the developmental screening questionnaire",
            "the bone age radiograph", "the newborn hearing screen",
            "the Denver developmental assessment",
            "the pubertal staging examination",
        ],
    },
    {
        "name": "Behavioral Health",
        "conditions": {
            "Mood disorders": [
                "major depressive disorder", "persistent depressive disorder",
                "bipolar I disorder", "bipolar II disorder",
                "cyclothymic disorder", "seasonal pattern depression",
                "postpartum mood episode",
                "substance-induced mood disorder",
            ],
            "Anxiety and related disorders": [
                "generalized anxiety disorder", "panic disorder",
                "agoraphobia", "social anxiety disorder",
                "specific phobia", "obsessive-compulsive disorder",
                "body dysmorphic disorder", "hoarding disorder",
            ],
            "Trauma and stressor-related disorders": [
                "post-traumatic stress disorder", "acute stress disorder",
                "adjustment disorder", "complicated grief",
                "reactive attachment disorder",
            ],
            "Psychotic disorders": [
                "schizophrenia", "schizoaffective disorder",
                "brief psychotic disorder", "delusional disorder",
                "schizophreniform disorder",
                "substance-induced psychotic disorder",
            ],
            "Substance use disorders": [
                "alcohol use disorder", "alcohol withdrawal syndrome",
                "opioid use disorder", "stimulant use disorder",
                "cannabis use disorder", "nicotine dependence",
                "benzodiazepine withdrawal", "inhalant use disorder",
            ],
            "Neurocognitive and somatic disorders": [
                "delirium", "major neurocognitive disorder",
                "mild neurocognitive disorder",
                "somatic symptom disorder", "conversion disorder",
                "illness anxiety disorder", "factitious disorder",
                "malingering",
            ],
            "Feeding, sleep and impulse control": [
                "anorexia nervosa", "bulimia nervosa",
                "binge eating disorder", "insomnia disorder",
                "narcolepsy", "restless legs syndrome",
                "intermittent explosive disorder",
                "oppositional defiant disorder",
            ],
            "Personality disorders": [
                "borderline personality disorder",
                "antisocial personality disorder",
                "narcissistic personality disorder",
                "avoidant personality disorder",
                "obsessive-compulsive personality disorder",
                "schizotypal personality disorder",
            ],
            "Risk assessment and crisis care": [
                "suicide risk assessment", "violence risk assessment",
                "involuntary psychiatric hold", "safety planning",
                "crisis de-escalation", "capacity assessment in psychosis",
            ],
        },
        "agents": [
            "sertraline", "fluoxetine", "lithium carbonate", "risperidone",
            "haloperidol", "clozapine", "lorazepam", "bupropion",
            "buprenorphine-naloxone", "naltrexone",
        ],
        "studies": [
            "the mental status examination",
            "the depression screening questionnaire",
            "the alcohol use screening instrument",
            "the cognitive screening instrument",
            "the serum lithium level", "urine drug screening",
        ],
    },
    {
        "name": "Social Sciences",
        "conditions": {
            "Communication and the clinical encounter": [
                "open-ended interviewing", "motivational interviewing",
                "breaking bad news", "shared decision making",
                "working with an interpreter", "health literacy assessment",
                "disclosure of medical error",
                "managing the difficult conversation",
            ],
            "Medical ethics": [
                "informed consent", "decision-making capacity",
                "advance directives", "surrogate decision making",
                "confidentiality and its limits",
                "withdrawal of life-sustaining treatment",
                "conflict of interest", "professional boundaries",
                "futility and non-beneficial treatment",
                "research ethics and the consent process",
            ],
            "Law and regulation in clinical practice": [
                "mandatory reporting of abuse",
                "reportable communicable disease",
                "duty to warn", "medical malpractice elements",
                "privacy of health information",
                "emergency treatment obligations",
                "licensure and scope of practice",
            ],
            "Systems-based practice and patient safety": [
                "root cause analysis", "the adverse event report",
                "the medication reconciliation process",
                "handoff communication", "checklists and forcing functions",
                "the just culture model",
                "human factors in device design",
                "the Swiss cheese model of system failure",
            ],
            "Health care delivery and policy": [
                "fee-for-service payment", "capitated payment",
                "value-based purchasing",
                "insurance coverage and cost sharing",
                "access barriers to care", "the medical home model",
                "the role of primary care in a health system",
                "pharmaceutical formulary management",
            ],
            "Social determinants and population health": [
                "the social gradient in health",
                "food insecurity and health",
                "housing instability and health",
                "structural racism and health outcomes",
                "occupational exposure and risk",
                "immigrant and refugee health needs",
                "rural access to specialty care",
                "community health worker programs",
            ],
        },
        "studies": [
            "the patient experience survey",
            "the quality indicator dashboard",
            "the incident report trend", "the care gap report",
            "the cost-effectiveness ratio",
            "the health equity audit",
        ],
    },
    {
        "name": "Biostatistics & Study Design",
        "conditions": {
            "Study designs": [
                "the randomized controlled trial", "the crossover trial",
                "the cluster randomized trial", "the cohort study",
                "the case-control study", "the cross-sectional study",
                "the case series", "the systematic review",
                "the meta-analysis", "the non-inferiority trial",
                "the pragmatic trial", "the stepped-wedge design",
            ],
            "Measures of occurrence and association": [
                "incidence", "prevalence", "relative risk",
                "the odds ratio", "the hazard ratio",
                "absolute risk reduction", "the number needed to treat",
                "the number needed to harm", "attributable risk",
                "the standardized mortality ratio",
            ],
            "Diagnostic test characteristics": [
                "sensitivity", "specificity",
                "the positive predictive value",
                "the negative predictive value", "the likelihood ratio",
                "the receiver operating characteristic curve",
                "the pre-test probability",
                "the effect of prevalence on predictive value",
            ],
            "Bias, confounding and validity": [
                "selection bias", "recall bias", "observer bias",
                "lead-time bias", "length-time bias", "confounding",
                "effect modification", "the healthy worker effect",
                "loss to follow-up", "intention-to-treat analysis",
                "regression to the mean", "immortal time bias",
            ],
            "Statistical inference": [
                "the null hypothesis", "the p value",
                "the confidence interval", "type I error",
                "type II error", "statistical power",
                "the sample size calculation", "multiple comparisons",
                "the t test", "the chi-square test",
                "analysis of variance", "linear regression",
                "logistic regression", "survival analysis",
                "the Kaplan-Meier curve",
            ],
            "Evidence appraisal": [
                "the hierarchy of evidence",
                "the risk of bias assessment",
                "publication bias", "the forest plot",
                "heterogeneity between studies",
                "the clinical practice guideline grading",
            ],
        },
        "studies": [
            "the trial flow diagram", "the baseline characteristics table",
            "the Kaplan-Meier survival plot", "the funnel plot",
            "the subgroup analysis", "the Bland-Altman plot",
        ],
    },
    {
        "name": "Genetics & Molecular Medicine",
        "structures": [
            "nuclear chromosome", "messenger RNA transcript", "ribosome",
            "mitochondrial genome", "DNA repair machinery",
        ],
        "conditions": {
            "Patterns of inheritance": [
                "autosomal dominant inheritance",
                "autosomal recessive inheritance",
                "X-linked recessive inheritance",
                "X-linked dominant inheritance",
                "mitochondrial inheritance", "genomic imprinting",
                "uniparental disomy", "incomplete penetrance",
                "variable expressivity", "anticipation",
                "mosaicism", "consanguinity and recessive risk",
            ],
            "Chromosomal disorders": [
                "trisomy 21", "trisomy 18", "trisomy 13",
                "Turner syndrome", "monosomy X mosaicism",
                "cri-du-chat syndrome", "DiGeorge microdeletion",
                "Prader-Willi syndrome", "Angelman syndrome",
                "balanced translocation carrier",
            ],
            "Single-gene disorders": [
                "cystic fibrosis", "Marfan syndrome",
                "Ehlers-Danlos syndrome", "neurofibromatosis type 1",
                "neurofibromatosis type 2", "tuberous sclerosis complex",
                "familial hypercholesterolemia",
                "hereditary hemorrhagic telangiectasia",
                "fragile X syndrome", "spinal muscular atrophy",
                "Friedreich ataxia", "alkaptonuria",
            ],
            "Inborn errors of metabolism": [
                "phenylketonuria", "homocystinuria",
                "maple syrup urine disease", "galactosemia",
                "glycogen storage disease type I",
                "Tay-Sachs disease", "Gaucher disease",
                "Niemann-Pick disease", "Fabry disease",
                "ornithine transcarbamylase deficiency",
                "medium-chain acyl-CoA dehydrogenase deficiency",
                "mitochondrial encephalomyopathy",
            ],
            "Cancer genetics": [
                "the two-hit hypothesis",
                "hereditary breast and ovarian cancer syndrome",
                "Lynch syndrome", "Li-Fraumeni syndrome",
                "retinoblastoma predisposition",
                "multiple endocrine neoplasia screening",
                "oncogene activation", "tumor suppressor loss",
                "microsatellite instability",
            ],
            "Molecular techniques and counselling": [
                "polymerase chain reaction",
                "Sanger sequencing", "next-generation sequencing",
                "chromosomal microarray", "fluorescence in situ hybridization",
                "Southern blotting", "the pedigree analysis",
                "pre-test genetic counselling",
                "variant of uncertain significance reporting",
                "carrier screening programs",
            ],
        },
        "studies": [
            "the karyotype", "the pedigree diagram",
            "the gene panel report", "the newborn screening result",
            "the carrier screening result",
            "the pharmacogenomic report",
        ],
    },
    {
        "name": "General Pharmacology",
        "structures": [
            "cell surface receptor", "ion channel", "enzyme active site",
            "hepatic cytochrome P450 system", "renal clearance pathway",
        ],
        "conditions": {
            "Pharmacokinetic principles": [
                "first-order elimination", "zero-order elimination",
                "volume of distribution", "clearance",
                "elimination half-life", "bioavailability",
                "first-pass metabolism", "steady-state concentration",
                "loading dose calculation",
                "maintenance dose calculation",
                "enterohepatic recirculation",
                "protein binding and free drug fraction",
            ],
            "Pharmacodynamic principles": [
                "the dose-response curve", "potency and efficacy",
                "full agonism", "partial agonism",
                "competitive antagonism", "non-competitive antagonism",
                "inverse agonism", "receptor desensitization",
                "the therapeutic index", "tachyphylaxis",
            ],
            "Drug interactions and metabolism": [
                "cytochrome P450 induction",
                "cytochrome P450 inhibition",
                "pharmacodynamic drug interaction",
                "the grapefruit juice interaction",
                "transporter-mediated interaction",
                "prodrug activation",
                "genetic polymorphism of drug metabolism",
            ],
            "Adverse drug reactions": [
                "type A dose-dependent reaction",
                "type B idiosyncratic reaction",
                "drug-induced liver injury",
                "drug-induced nephrotoxicity",
                "drug-induced QT prolongation",
                "drug-induced agranulocytosis",
                "serotonin syndrome",
                "neuroleptic malignant syndrome",
                "drug-induced lupus",
                "medication error at prescribing",
            ],
            "Special populations and prescribing": [
                "prescribing in renal impairment",
                "prescribing in hepatic impairment",
                "prescribing in pregnancy",
                "prescribing in the older adult",
                "weight-based paediatric dosing",
                "therapeutic drug monitoring",
                "deprescribing review",
            ],
            "Autonomic pharmacology": [
                "cholinergic agonism", "antimuscarinic effect",
                "alpha-1 adrenergic blockade",
                "beta-1 adrenergic blockade",
                "beta-2 adrenergic agonism",
                "indirect sympathomimetic action",
                "ganglionic blockade",
            ],
        },
        "agents": [
            "atropine", "neostigmine", "phenylephrine", "propranolol",
            "dobutamine", "clonidine", "prazosin", "succinylcholine",
            "morphine", "ibuprofen", "acetaminophen", "ketamine",
        ],
        "studies": [
            "the plasma concentration-time curve",
            "the trough drug level",
            "the creatinine clearance estimate",
            "the drug interaction check",
            "the adverse event causality assessment",
            "the dose-response experiment",
        ],
    },
)


# ---------------------------------------------------------------------------
# Deliberate cross-listings: the polyhierarchy.
#
# Each name is placed under every (root, category) pair listed, so the loader
# reports it as multi-parent and the seeder gives it one canonical node with
# several parent edges. These are chosen because the topic genuinely belongs
# in each place -- a student filing a question about hypertension in pregnancy
# is not making a mistake -- which is the whole reason WIMI's hierarchy is a
# DAG rather than a tree.
# ---------------------------------------------------------------------------

CROSS_LISTINGS: tuple[tuple[str, tuple[tuple[str, str], ...]], ...] = (
    ("hypertension", (
        ("Cardiovascular System", "Vascular disorders"),
        ("Renal & Urinary System", "Vascular and hypertensive disorders"),
        ("Endocrine System", "Disorders of the adrenal gland"),
        ("Pregnancy and the Puerperium",
         "Medical disorders complicating pregnancy"),
    )),
    ("deep venous thrombosis", (
        ("Cardiovascular System", "Vascular disorders"),
        ("Pregnancy and the Puerperium",
         "Medical disorders complicating pregnancy"),
        ("Multisystem Processes & Disorders",
         "Oncologic emergencies and paraneoplastic processes"),
    )),
    ("sepsis", (
        ("Multisystem Processes & Disorders", "Shock and critical illness"),
        ("Immune System", "Inflammation"),
        ("Blood & Lymphoreticular System",
         "Disorders of platelets and coagulation"),
    )),
    ("diabetes mellitus", (
        ("Endocrine System", "Disorders of glucose regulation"),
        ("Multisystem Processes & Disorders",
         "Nutritional and metabolic disorders"),
        ("Renal & Urinary System", "Glomerular disorders"),
    )),
    ("asthma", (
        ("Respiratory System", "Obstructive disorders"),
        ("Immune System", "Immunologic and allergic disorders"),
    )),
    ("pulmonary embolism", (
        ("Respiratory System", "Vascular disorders"),
        ("Cardiovascular System", "Vascular disorders"),
        ("Pregnancy and the Puerperium",
         "Medical disorders complicating pregnancy"),
    )),
    ("anemia of chronic disease", (
        ("Blood & Lymphoreticular System", "Disorders of the erythrocyte"),
        ("Renal & Urinary System", "Tubulointerstitial disorders"),
    )),
    ("systemic lupus erythematosus", (
        ("Immune System", "Autoimmune disorders"),
        ("Renal & Urinary System", "Glomerular disorders"),
        ("Skin & Subcutaneous Tissue",
         "Bullous and immune-mediated disorders"),
    )),
    ("sarcoidosis", (
        ("Respiratory System", "Restrictive and interstitial disorders"),
        ("Immune System", "Inflammation"),
        ("Nervous System & Special Senses",
         "Degenerative and demyelinating disorders"),
    )),
    ("pulmonary tuberculosis", (
        ("Microbiology & Infectious Disease",
         "Mycobacterial and spirochetal organisms"),
        ("Respiratory System", "Restrictive and interstitial disorders"),
    )),
    ("hyperkalemia", (
        ("Renal & Urinary System", "Disorders of fluid and electrolytes"),
        ("Cardiovascular System", "Disorders of rhythm and conduction"),
        ("Endocrine System", "Disorders of the adrenal gland"),
    )),
    ("hypercalcemia of malignancy", (
        ("Renal & Urinary System", "Disorders of fluid and electrolytes"),
        ("Multisystem Processes & Disorders",
         "Oncologic emergencies and paraneoplastic processes"),
        ("Endocrine System", "Disorders of calcium and bone metabolism"),
    )),
    ("gout", (
        ("Musculoskeletal System",
         "Inflammatory and autoimmune arthropathies"),
        ("Renal & Urinary System", "Obstructive and structural disorders"),
    )),
    ("osteoporosis", (
        ("Musculoskeletal System", "Degenerative and metabolic bone disease"),
        ("Endocrine System", "Disorders of calcium and bone metabolism"),
        ("Female Reproductive System", "Menopause and the climacteric"),
    )),
    ("rhabdomyolysis", (
        ("Musculoskeletal System", "Disorders of muscle"),
        ("Renal & Urinary System", "Tubulointerstitial disorders"),
        ("Multisystem Processes & Disorders",
         "Environmental and occupational injury"),
    )),
    ("tumor lysis syndrome", (
        ("Multisystem Processes & Disorders",
         "Oncologic emergencies and paraneoplastic processes"),
        ("Renal & Urinary System", "Tubulointerstitial disorders"),
        ("Blood & Lymphoreticular System", "Disorders of leukocytes"),
    )),
    ("preeclampsia", (
        ("Pregnancy and the Puerperium", "Antepartum complications"),
        ("Cardiovascular System", "Vascular disorders"),
        ("Renal & Urinary System", "Vascular and hypertensive disorders"),
    )),
    ("gestational diabetes mellitus", (
        ("Pregnancy and the Puerperium", "Antepartum complications"),
        ("Endocrine System", "Disorders of glucose regulation"),
    )),
    ("polycystic ovary syndrome", (
        ("Female Reproductive System", "Disorders of the menstrual cycle"),
        ("Endocrine System", "Multiple endocrine disorders"),
        ("Multisystem Processes & Disorders",
         "Nutritional and metabolic disorders"),
    )),
    ("cystic fibrosis", (
        ("Genetics & Molecular Medicine", "Single-gene disorders"),
        ("Respiratory System", "Obstructive disorders"),
        ("Gastrointestinal System", "Pancreatic disorders"),
    )),
    ("sickle cell disease", (
        ("Genetics & Molecular Medicine", "Single-gene disorders"),
        ("Blood & Lymphoreticular System", "Disorders of the erythrocyte"),
        ("Musculoskeletal System",
         "Degenerative and metabolic bone disease"),
    )),
    ("Marfan syndrome", (
        ("Genetics & Molecular Medicine", "Single-gene disorders"),
        ("Cardiovascular System", "Structural and congenital disorders"),
        ("Nervous System & Special Senses",
         "Disorders of the special senses"),
    )),
    ("Down syndrome", (
        ("Genetics & Molecular Medicine", "Chromosomal disorders"),
        ("Human Development", "Disorders of development"),
        ("Cardiovascular System", "Structural and congenital disorders"),
    )),
    ("Klinefelter syndrome", (
        ("Male Reproductive System", "Developmental disorders"),
        ("Genetics & Molecular Medicine", "Chromosomal disorders"),
    )),
    ("Turner syndrome", (
        ("Genetics & Molecular Medicine", "Chromosomal disorders"),
        ("Female Reproductive System", "Menopause and the climacteric"),
        ("Cardiovascular System", "Structural and congenital disorders"),
    )),
    ("Huntington disease", (
        ("Nervous System & Special Senses",
         "Degenerative and demyelinating disorders"),
        ("Genetics & Molecular Medicine", "Patterns of inheritance"),
        ("Behavioral Health", "Neurocognitive and somatic disorders"),
    )),
    ("delirium", (
        ("Behavioral Health", "Neurocognitive and somatic disorders"),
        ("Multisystem Processes & Disorders", "Aging and frailty"),
    )),
    ("alcohol use disorder", (
        ("Behavioral Health", "Substance use disorders"),
        ("Gastrointestinal System", "Hepatic and biliary disorders"),
        ("Social Sciences", "Social determinants and population health"),
    )),
    ("opioid overdose", (
        ("Multisystem Processes & Disorders",
         "Environmental and occupational injury"),
        ("Behavioral Health", "Substance use disorders"),
        ("Respiratory System",
         "Disorders of gas exchange and ventilation"),
    )),
    ("obesity", (
        ("Multisystem Processes & Disorders",
         "Nutritional and metabolic disorders"),
        ("Endocrine System", "Disorders of glucose regulation"),
        ("Respiratory System",
         "Disorders of gas exchange and ventilation"),
    )),
    ("metabolic syndrome", (
        ("Multisystem Processes & Disorders",
         "Nutritional and metabolic disorders"),
        ("Cardiovascular System", "Vascular disorders"),
    )),
    ("hypothyroidism", (
        ("Endocrine System", "Disorders of the thyroid gland"),
        ("Behavioral Health", "Mood disorders"),
        ("Pregnancy and the Puerperium",
         "Medical disorders complicating pregnancy"),
    )),
    ("iron deficiency anemia", (
        ("Blood & Lymphoreticular System", "Disorders of the erythrocyte"),
        ("Gastrointestinal System", "Disorders of the intestine"),
        ("Female Reproductive System", "Disorders of the menstrual cycle"),
    )),
    ("vitamin D deficiency", (
        ("Endocrine System", "Disorders of calcium and bone metabolism"),
        ("Multisystem Processes & Disorders",
         "Nutritional and metabolic disorders"),
        ("Musculoskeletal System",
         "Degenerative and metabolic bone disease"),
    )),
    ("Clostridioides difficile colitis", (
        ("Microbiology & Infectious Disease",
         "Health care associated infection"),
        ("Gastrointestinal System", "Disorders of the intestine"),
    )),
    ("human immunodeficiency virus infection", (
        ("Microbiology & Infectious Disease", "Viral infections"),
        ("Immune System", "Immunodeficiency"),
    )),
    ("syphilis", (
        ("Microbiology & Infectious Disease",
         "Mycobacterial and spirochetal organisms"),
        ("Nervous System & Special Senses",
         "Degenerative and demyelinating disorders"),
        ("Pregnancy and the Puerperium", "Antepartum complications"),
    )),
    ("pelvic inflammatory disease", (
        ("Female Reproductive System",
         "Infectious and inflammatory disorders"),
        ("Microbiology & Infectious Disease", "Gram-negative organisms"),
    )),
    ("osteomyelitis", (
        ("Musculoskeletal System", "Infectious disorders"),
        ("Skin & Subcutaneous Tissue", "Infectious disorders"),
    )),
    ("cellulitis", (
        ("Skin & Subcutaneous Tissue", "Infectious disorders"),
        ("Microbiology & Infectious Disease", "Gram-positive organisms"),
    )),
    ("melanoma", (
        ("Skin & Subcutaneous Tissue", "Neoplastic disorders"),
        ("Nervous System & Special Senses", "Neoplastic disorders"),
    )),
    ("multiple myeloma", (
        ("Blood & Lymphoreticular System",
         "Disorders of the lymphoreticular system"),
        ("Renal & Urinary System", "Tubulointerstitial disorders"),
        ("Musculoskeletal System", "Neoplastic disorders"),
    )),
    ("Hodgkin lymphoma", (
        ("Blood & Lymphoreticular System",
         "Disorders of the lymphoreticular system"),
        ("Respiratory System", "Pleural and mediastinal disorders"),
    )),
    ("renal cell carcinoma", (
        ("Renal & Urinary System", "Neoplastic disorders"),
        ("Multisystem Processes & Disorders",
         "Oncologic emergencies and paraneoplastic processes"),
    )),
    ("hepatocellular carcinoma", (
        ("Gastrointestinal System", "Neoplastic disorders"),
        ("Microbiology & Infectious Disease", "Viral infections"),
    )),
    ("adenocarcinoma of the prostate", (
        ("Male Reproductive System", "Neoplastic disorders"),
        ("Musculoskeletal System", "Neoplastic disorders"),
    )),
    ("invasive ductal carcinoma of the breast", (
        ("Female Reproductive System", "Malignant neoplasms"),
        ("Genetics & Molecular Medicine", "Cancer genetics"),
    )),
    ("adenocarcinoma of the colon", (
        ("Gastrointestinal System", "Neoplastic disorders"),
        ("Genetics & Molecular Medicine", "Cancer genetics"),
    )),
    ("small cell carcinoma of the lung", (
        ("Respiratory System", "Neoplastic disorders"),
        ("Endocrine System", "Multiple endocrine disorders"),
        ("Nervous System & Special Senses",
         "Disorders of the peripheral nerve and muscle"),
    )),
    ("myasthenia gravis", (
        ("Nervous System & Special Senses",
         "Disorders of the peripheral nerve and muscle"),
        ("Immune System", "Autoimmune disorders"),
        ("Respiratory System",
         "Disorders of gas exchange and ventilation"),
    )),
    ("multiple sclerosis", (
        ("Nervous System & Special Senses",
         "Degenerative and demyelinating disorders"),
        ("Immune System", "Autoimmune disorders"),
        ("Renal & Urinary System", "Obstructive and structural disorders"),
    )),
    ("ischemic stroke", (
        ("Nervous System & Special Senses", "Cerebrovascular disorders"),
        ("Cardiovascular System", "Disorders of rhythm and conduction"),
    )),
    ("giant cell arteritis", (
        ("Cardiovascular System", "Vascular disorders"),
        ("Immune System", "Autoimmune disorders"),
        ("Nervous System & Special Senses",
         "Disorders of the special senses"),
    )),
    ("sleep apnea", (
        ("Respiratory System",
         "Disorders of gas exchange and ventilation"),
        ("Cardiovascular System", "Vascular disorders"),
        ("Behavioral Health", "Feeding, sleep and impulse control"),
    )),
    ("anaphylaxis", (
        ("Immune System", "Immunologic and allergic disorders"),
        ("Multisystem Processes & Disorders", "Shock and critical illness"),
    )),
    ("disseminated intravascular coagulation", (
        ("Blood & Lymphoreticular System",
         "Disorders of platelets and coagulation"),
        ("Multisystem Processes & Disorders", "Shock and critical illness"),
        ("Pregnancy and the Puerperium", "Postpartum disorders"),
    )),
    ("postpartum depression", (
        ("Pregnancy and the Puerperium", "Postpartum disorders"),
        ("Behavioral Health", "Mood disorders"),
    )),
    ("neonatal hyperbilirubinemia", (
        ("Human Development", "Prenatal and neonatal development"),
        ("Blood & Lymphoreticular System", "Disorders of the erythrocyte"),
        ("Gastrointestinal System", "Hepatic and biliary disorders"),
    )),
    ("cerebral palsy", (
        ("Human Development", "Disorders of development"),
        ("Nervous System & Special Senses",
         "Traumatic and mechanical disorders"),
    )),
    ("autism spectrum disorder", (
        ("Human Development", "Disorders of development"),
        ("Behavioral Health", "Neurocognitive and somatic disorders"),
    )),
    ("lead poisoning", (
        ("Multisystem Processes & Disorders",
         "Environmental and occupational injury"),
        ("Human Development", "Disorders of development"),
        ("Blood & Lymphoreticular System", "Disorders of the erythrocyte"),
    )),
    ("informed consent", (
        ("Social Sciences", "Medical ethics"),
        ("Biostatistics & Study Design", "Evidence appraisal"),
    )),
    ("serotonin syndrome", (
        ("General Pharmacology", "Adverse drug reactions"),
        ("Behavioral Health", "Mood disorders"),
        ("Nervous System & Special Senses",
         "Seizure and paroxysmal disorders"),
    )),
    ("drug-induced liver injury", (
        ("General Pharmacology", "Adverse drug reactions"),
        ("Gastrointestinal System", "Hepatic and biliary disorders"),
    )),
    ("drug-induced QT prolongation", (
        ("General Pharmacology", "Adverse drug reactions"),
        ("Cardiovascular System", "Disorders of rhythm and conduction"),
    )),
    ("acetaminophen overdose", (
        ("Multisystem Processes & Disorders",
         "Environmental and occupational injury"),
        ("Gastrointestinal System", "Hepatic and biliary disorders"),
        ("General Pharmacology", "Adverse drug reactions"),
    )),
    ("prescribing in renal impairment", (
        ("General Pharmacology", "Special populations and prescribing"),
        ("Renal & Urinary System", "Tubulointerstitial disorders"),
    )),
    ("polypharmacy", (
        ("Multisystem Processes & Disorders", "Aging and frailty"),
        ("General Pharmacology", "Special populations and prescribing"),
        ("Social Sciences", "Systems-based practice and patient safety"),
    )),
    ("food insecurity and health", (
        ("Social Sciences", "Social determinants and population health"),
        ("Multisystem Processes & Disorders",
         "Nutritional and metabolic disorders"),
    )),
    ("the number needed to treat", (
        ("Biostatistics & Study Design",
         "Measures of occurrence and association"),
        ("Social Sciences", "Health care delivery and policy"),
    )),
)


# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------


def _expand(root: dict) -> list[dict]:
    """Turn one ROOTS entry into its ordered list of child category nodes.

    A container is ``{"name": ..., "children": [...]}``; a topic is a bare
    string in a container's ``children``. One representation each, so the
    loader never has to guess which it is holding.
    """
    categories: list[dict] = []

    structures = root.get("structures")
    if structures:
        categories.append({
            "name": STRUCTURE_CATEGORY,
            "children": [pattern.format(structure)
                         for structure in structures
                         for pattern in STRUCTURE_PATTERNS],
        })

    for category, content in root["conditions"].items():
        if isinstance(content, dict):
            children: list = [
                {"name": sub, "children": list(leaves)}
                for sub, leaves in content.items()
            ]
        else:
            children = list(content)
        categories.append({"name": category, "children": children})

    organisms = root.get("organisms")
    if organisms:
        categories.append({
            "name": ORGANISM_CATEGORY,
            "children": [
                {"name": syndrome,
                 "children": [f"{bug} {syndrome}" for bug in bugs]}
                for syndrome, bugs in organisms
            ],
        })

    agents = root.get("agents")
    if agents:
        categories.append({
            "name": AGENT_CATEGORY,
            "children": [pattern.format(agent)
                         for agent in agents
                         for pattern in AGENT_PATTERNS],
        })

    studies = root.get("studies")
    if studies:
        categories.append({
            "name": STUDY_CATEGORY,
            "children": [STUDY_PATTERN.format(study) for study in studies],
        })

    return categories


def _containers(node: dict):
    """Yield every container dict at or beneath ``node``."""
    yield node
    for child in node["children"]:
        if not isinstance(child, str):
            yield from _containers(child)


def _find_category(tree: list[dict], root_name: str, category: str) -> dict:
    for root in tree:
        if root["name"] != root_name:
            continue
        for node in _containers(root):
            if node is not root and node["name"] == category:
                return node
        raise SystemExit(
            f"no category {category!r} under root {root_name!r}"
        )
    raise SystemExit(f"no root named {root_name!r}")


def _apply_cross_listings(tree: list[dict]) -> None:
    for name, placements in CROSS_LISTINGS:
        if len(placements) < 2:
            raise SystemExit(f"cross-listing {name!r} names one parent only")
        for root_name, category in placements:
            node = _find_category(tree, root_name, category)
            if any(not isinstance(child, str) for child in node["children"]):
                raise SystemExit(
                    f"cross-listing {name!r} targets {category!r}, which "
                    "holds subcategories rather than topics"
                )
            if name in node["children"]:
                continue
            node["children"].append(name)


def _walk(
    node: dict,
    path: tuple[str, ...],
    out: list[tuple[str, tuple[str, ...]]],
) -> None:
    for child in node["children"]:
        if isinstance(child, str):
            out.append((child, path + (node["name"],)))
        else:
            _walk(child, path + (node["name"],), out)


def _check_structure(tree: list[dict]) -> dict:
    """Validate the tree and return the counts the fixture advertises."""
    leaves: list[tuple[str, tuple[str, ...]]] = []
    for root in tree:
        _walk(root, (), leaves)

    container_names = {
        node["name"] for root in tree for node in _containers(root)
    }

    by_name: dict[str, set[tuple[str, ...]]] = {}
    for name, path in leaves:
        by_name.setdefault(name, set()).add(path)

    # A topic listed twice under ONE parent is an authoring slip: the seeder
    # silently drops the second, so it would look like a cross-listing that
    # did nothing.
    seen: set[tuple[str, tuple[str, ...]]] = set()
    for pair in leaves:
        if pair in seen:
            raise SystemExit(f"topic {pair[0]!r} listed twice under {pair[1]}")
        seen.add(pair)

    # A topic sharing a name with a category or root would make the seeder's
    # path and name lookups disagree about which node is which.
    clash = container_names & set(by_name)
    if clash:
        raise SystemExit(f"topic name also used as a container: {sorted(clash)}")

    multi = sorted(name for name, paths in by_name.items() if len(paths) >= 2)
    if len(multi) < 50:
        raise SystemExit(f"only {len(multi)} multi-parent topics; need >= 50")
    for required in ("hypertension", "deep venous thrombosis"):
        if required not in multi:
            raise SystemExit(f"{required!r} must be multi-parent")

    # Nodes the seeder will create: one per distinct leaf name, plus one per
    # distinct container path. ``test_foldersync_roundtrip`` wants > 2,000.
    container_paths: set[tuple[str, ...]] = set()

    def _record(node: dict, path: tuple[str, ...]) -> None:
        here = path + (node["name"],)
        container_paths.add(here)
        for child in node["children"]:
            if not isinstance(child, str):
                _record(child, here)

    for root in tree:
        _record(root, ())
    nodes = len(by_name) + len(container_paths)
    if nodes <= 2100:
        raise SystemExit(
            f"the fixture would seed {nodes} nodes; "
            "test_foldersync_roundtrip wants more than 2,000 with margin"
        )

    return {
        "roots": len(tree),
        "containers": len(container_paths),
        "topic_listings": len(leaves),
        "distinct_topics": len(by_name),
        "multi_parent_topics": len(multi),
        "seeded_nodes_expected": nodes,
    }


def _check_priming_terms(text: str) -> int:
    """Every speech-to-text priming term must be in the fixture verbatim.

    Mirrors ``tests/test_stt_measure.py``'s check exactly, so a missing term
    fails here rather than in a test somebody has to go and diagnose.
    """
    corpus = json.loads(CORPUS_PATH.read_text(encoding="utf-8"))
    terms = list(corpus["priming"]["base_terms"])
    for utterance in corpus["utterances"]:
        terms.extend(utterance.get("priming_entry_terms", []))

    haystack = " ".join(text.lower().split())
    missing = [term for term in dict.fromkeys(terms)
               if " ".join(term.lower().split()) not in haystack]
    if missing:
        raise SystemExit(
            "these priming terms are not in the fixture: " + repr(missing)
        )
    return len(dict.fromkeys(terms))


def build() -> str:
    tree = [
        {"name": root["name"], "children": _expand(root)}
        for root in ROOTS
    ]
    _apply_cross_listings(tree)
    counts = _check_structure(tree)

    document = {
        "fixture_id": "exam-outline-synthetic-v1",
        "synthetic": True,
        "generated_by": "tests/fixtures/build_exam_outline.py",
        "exam_name": EXAM_NAME,
        "description": (
            "A synthetic multi-level exam content outline for tests that need "
            "a realistic subject hierarchy. The terminology is real medical "
            "vocabulary; the structure, category names, ordering and selection "
            "are this project's own and are not taken from any published "
            "outline. It replaces a verbatim copy of a third party's content "
            "outline (#437)."
        ),
        "counts": counts,
        "roots": tree,
    }
    text = json.dumps(document, indent=2, ensure_ascii=True) + "\n"
    counts["priming_terms_checked"] = _check_priming_terms(text)
    # Re-render so the advertised counts include the priming figure.
    document["counts"] = counts
    return json.dumps(document, indent=2, ensure_ascii=True) + "\n"


def main(argv: list[str]) -> int:
    text = build()
    if "--check" in argv:
        current = OUTLINE_PATH.read_text(encoding="utf-8") if OUTLINE_PATH.exists() else ""
        if current != text:
            print("exam_outline.json is stale; re-run this script", file=sys.stderr)
            return 1
        print("exam_outline.json is up to date")
        return 0
    OUTLINE_PATH.write_text(text, encoding="utf-8")
    print(f"wrote {OUTLINE_PATH} ({len(text):,} bytes)")
    for key, value in json.loads(text)["counts"].items():
        print(f"  {key}: {value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
