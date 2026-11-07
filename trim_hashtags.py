"""Keep the description text but cut hashtags to a few strong ones: #shorts + #didyouknow (or #facts)
plus up to 2 topic-specific ones from the generated list."""
import os, re, sys
d = os.environ.get("DESCRIPTION", "")
d = re.sub(r"\s*#didyouknow\b", "", d, flags=re.I).strip()   # this hashtag is no longer wanted
if os.environ.get("TRIM_HASHTAGS", "0") != "1":   # restored: keep every hashtag the script writer produced
    print(d)
    sys.exit(0)
tags = re.findall(r"#\w+", d)
text = re.sub(r"\s*#\w+", "", d).strip()
generic = {"#fyp", "#viral", "#explore", "#trending", "#foryou", "#foryoupage", "#shorts", "#facts",
           "#didyouknow", "#youtubeshorts", "#fact", "#amazing", "#interesting", "#shortsfeed"}
low = [t.lower() for t in tags]
specific = []
for t in tags:
    if t.lower() not in generic and t.lower() not in [s.lower() for s in specific]:
        specific.append(t)
final = specific[-3:]
print(f"{text} {' '.join(final)}".strip())
