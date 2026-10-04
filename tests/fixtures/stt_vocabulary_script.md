<!--
GENERATED FILE -- do not edit by hand.

Source: tests/fixtures/stt_vocabulary_terms.json
Regenerate: python scripts/stt_measure.py write-script
Gate:       python scripts/stt_measure.py check-script  (tests/test_stt_measure.py)

The reference transcripts in the JSON are what the scorer compares against, so
an edit here that does not reach the JSON would silently score the recording
against the wrong words.
-->

# Read-aloud script -- speech-to-text measurement (#59, task T3)

This is the corpus for the transcription-accuracy measurement that #59's
acceptance criterion asks for. **It has to be your voice.** A synthetic voice
reading this measures the text-to-speech engine's pronunciation, not whether
this feature works for you.

## Before you start

- **Record where you will actually use the feature.** Same laptop, same room,
  same distance from the microphone, same time of night. If you study with a
  fan on, leave the fan on. The measurement is worthless if it is made under
  conditions the feature will never see.
- **One file per utterance.** 24 files in one directory.
- **Name each file after its utterance id**: `u01.wav`, `u02.wav`, and so on.
  The scorer matches by that name and will tell you which ones it could not
  find.
- **Format: mono WAV.** 16 kHz 16-bit is preferred because it is what the
  engine works in natively. It is *not* required -- whisper.cpp resamples
  internally and accepts wav, flac, mp3 and ogg at any rate -- so if your
  recorder only does 44.1 kHz stereo, use it and do not spend time converting.
- **Read at your normal speaking pace**, the way you would actually talk to the
  app at the end of a question block. Hesitation is realistic. Do not perform.
- **If you fluff a line, re-record that one file.** Do not stitch takes
  together and do not read the whole script again.
- Read the punctuation as pauses, not as words.

The whole thing is about 7 minutes of speech. Budget twice that.

## Why 24 utterances and not more

The metric's denominator is **marked terms**, not utterances, and this corpus
carries 111 of them in 24 readings. That is enough to tell 95% recall
from 90% (about +/-4 percentage points at 95%), which is the distinction the
pass bar actually turns on. Doubling the utterance count would narrow that to
about +/-3 points and double the reading -- and a corpus abandoned at utterance
35 measures nothing at all.

## Pronunciation notes

Some of these are deliberately about *how* an abbreviation is said, so read
them the way the note says. Getting this wrong makes the reference transcript
wrong, which is worse than a bad model.

## The script


### u01 -- save as `u01.wav`

> **Note:** Control. No domain vocabulary at all. If WER is bad here the problem is the recording, not the model.

Okay, so the reason I got this one wrong is that I was rushing and I read the last line of the question first. I knew the material, I just answered the question I expected instead of the question that was actually on the screen.

### u02 -- save as `u02.wav`

So essential hypertension is usually managed by lowering the volume first, which is why hydrochlorothiazide comes early. If that is not enough you add an ACE inhibitor like lisinopril, and the reason you check a creatinine afterwards is that the ACE inhibitor drops the filtration pressure inside the glomerulus.

### u03 -- save as `u03.wav`

The thing I missed is that warfarin takes about five days to actually work, so in a deep venous thrombosis you bridge with heparin until the INR is between two and three. If you start warfarin alone the protein C drops first and the patient clots more, not less.

### u04 -- save as `u04.wav`

COPD is really two diseases wearing one name. Chronic bronchitis is a mucus problem and emphysema is a destruction problem, and the reason that matters is that the emphysema patient is the one whose chest stays hyperinflated even after you have treated the bronchitis.

### u05 -- save as `u05.wav`

GERD is a pressure problem at the lower esophageal sphincter, not an acid overproduction problem, which is why a proton pump inhibitor helps the symptoms but does not fix the mechanism. That is also why the question asked about the hiatal hernia rather than about the acid.

### u06 -- save as `u06.wav`

Heparin induced thrombocytopenia confused me because the platelet count falls and yet the patient clots. The antibody activates the platelets rather than destroying them, so it is nothing like immune thrombocytopenic purpura, or ITP, where the platelets are simply cleared by the spleen.

### u07 -- save as `u07.wav`

The difference I keep forgetting is the timing. Poststreptococcal glomerulonephritis shows up about two weeks after the sore throat, whereas IgA nephropathy gives you blood in the urine during the infection itself. Same hematuria, completely different story.

### u08 -- save as `u08.wav`

> **Note:** ARDS is spoken as a word, not as letters: say 'ards'. Read '6 ml per kg' as 'six milliliters per kilogram'.

Acute respiratory distress syndrome, which everyone just says as ARDS, is a permeability problem, so the fluid is protein rich and the wedge pressure stays under eighteen. You ventilate with a low tidal volume, around 6 ml per kg, to keep the lung from tearing itself further.

### u09 -- save as `u09.wav`

> **Note:** NSTEMI is spoken as a word: 'en-stemmy'. Read '0.9' as 'zero point nine'.

An NSTEMI means the troponin is up but the ST segments are not, so the artery is only partly closed. The reason I got it wrong is that I treated a troponin of 0.9 as a rule out, when the trend over three hours is what actually matters.

### u10 -- save as `u10.wav`

> **Note:** MRSA is spoken as a word: 'mersa'.

If the wound culture grows MRSA, nafcillin is useless, because the resistance lives in the binding protein and not in a beta lactamase. You go to vancomycin, and you check a trough, because the kidney is what pays for it.

### u11 -- save as `u11.wav`

> **Note:** CABG is spoken as a word: 'cabbage'.

The thing that clicked for me is that a CABG goes around the blockage and a stent goes through it. Left main disease and diabetes both push you towards the bypass, which is why the answer was surgery and not the catheterization lab.

### u12 -- save as `u12.wav`

> **Note:** Read '6.4' as 'six point four'.

In rhabdomyolysis the muscle dumps myoglobin and potassium into the blood at the same time, so a potassium of 6.4 is the thing that kills the patient long before the kidney ever fails. Fluids first, and you watch the electrocardiogram, not the creatine kinase.

### u13 -- save as `u13.wav`

> **Note:** Read HLA B27 as 'H L A B twenty seven'.

Ankylosing spondylitis is the one where the back pain gets better with movement, which is backwards from every other kind of back pain. It is HLA B27 associated, and the reason they showed the chest x ray is that the same disease scars the upper lobes.

### u14 -- save as `u14.wav`

Pheochromocytoma is episodic because the tumor releases catecholamines in bursts, so the blood pressure is normal in between the attacks. You block alpha first with phenoxybenzamine and only then beta, because if you block beta first the unopposed alpha makes the pressure worse.

### u15 -- save as `u15.wav`

> **Note:** Read 'A1c' as 'A one C' and '9.4' as 'nine point four'.

Metformin works mostly by shutting down hepatic gluconeogenesis, which is why it does not cause hypoglycemia on its own. With a hemoglobin A1c of 9.4 you are well past the point where one drug will do it, and that is what the question was really asking.

### u16 -- save as `u16.wav`

Amiodarone is the drug that does a little of every class, so it prolongs the QT and it can throw the patient into torsades de pointes. The fix in the moment is magnesium, and the longer term problem is the thyroid and the lung, which is where the pulmonary fibrosis comes from.

### u17 -- save as `u17.wav`

In Wolff Parkinson White there is an accessory pathway, so if you give a node blocker like adenosine or a calcium channel blocker you push everything down the accessory pathway instead. That is how a stable patient ends up in ventricular fibrillation.

### u18 -- save as `u18.wav`

Pyelonephritis is a cystitis that climbed, so the giveaway is the flank tenderness and the fever, not the burning. You treat it for fourteen days rather than three, and ceftriaxone is reasonable while you are waiting for the urine culture.

### u19 -- save as `u19.wav`

In cirrhosis the ascites comes from portal hypertension plus a low albumin, so the diuretic pair is spironolactone together with furosemide. Spironolactone on its own is too slow, and furosemide on its own drops the potassium straight through the floor.

### u20 -- save as `u20.wav`

> **Note:** Control. No domain vocabulary.

I actually understood the concept here. What went wrong is that there were two answers that were both true, and I picked the one that was true in general instead of the one that was true for this particular patient. That is a reading problem, not a knowledge problem.

### u21 -- save as `u21.wav`

The trap in this one was the brand names. Lopressor is metoprolol, Coumadin is warfarin, and Lasix is furosemide, and the stem used the brand name for one of them and the generic name for the other two, so that you would not notice they were all the same question.

### u22 -- save as `u22.wav`

> **Note:** GFR, BUN and ATN are all spoken as letters. Read '10 to 1' as 'ten to one'.

A GFR of thirty means you have to redose almost everything, and the reason they gave the BUN to creatinine ratio was to separate a prerenal picture from acute tubular necrosis. In ATN the ratio is closer to 10 to 1, because the tubule has stopped reabsorbing.

### u23 -- save as `u23.wav`

Necrotizing fasciitis hurts far more than it looks like it ought to, and that mismatch is the whole diagnosis. Osteomyelitis is the slower version of the same idea, where the imaging lags the infection by about two weeks, so a normal x ray early does not rule it out.

### u24 -- save as `u24.wav`

> **Note:** Control. No domain vocabulary. Deliberately last, so the reader finishes on an easy one.

So what I am going to do differently is slow down on the last two lines of the stem. Every single time I have missed one of these it has been because I answered quickly and confidently, and confidence is not the same thing as being right.

---

When all 24 files exist, run the measurement -- see the module docstring of `scripts/stt_measure.py` for the exact command.
