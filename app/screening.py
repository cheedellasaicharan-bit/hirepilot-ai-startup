import re
STOP = set("a an and are as at be by for from has have in into is it its of on or our that the their this to using was were will with you your job role work experience skills required preferred candidate strong good team years year".split())
def terms(text):
    return list(dict.fromkeys(w for w in re.findall(r"[a-zA-Z][a-zA-Z0-9+#.-]{1,}", text.lower()) if w not in STOP and len(w) > 2))
def evaluate(description, resume):
    wanted = terms(description)
    got = set(terms(resume))
    matched = [w for w in wanted if w in got]
    missing = [w for w in wanted if w not in got]
    score = round((len(matched) / len(wanted)) * 100, 1) if wanted else 0.0
    return {"score": score, "matched": matched[:20], "missing": missing[:15],
            "explanation": "Score measures keyword overlap only. It is not a probability of job performance or a hiring recommendation."}
