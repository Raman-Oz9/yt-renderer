"""Description cleanup: drop generic reach-bait hashtags (#fyp, #viral, #foryou, #shorts, ...) and keep only
hashtags that relate to the video's topic."""
import os, re, sys
d = os.environ.get("DESCRIPTION", "")
generic = {"fyp", "viral", "explore", "trending", "foryou", "foryoupage", "shorts", "short", "facts", "fact",
           "didyouknow", "youtubeshorts", "youtubeshort", "amazing", "interesting", "shortsfeed", "shortsvideo",
           "reels", "tiktok", "subscribe", "like", "follow", "fy", "foryoupageシ", "mustwatch", "wow", "explorepage",
           "funfacts", "randomfacts", "learnsomethingnew", "dailyfacts", "mindblowing", "mindblown", "knowledge"}
d = re.sub(r"\s*#(\w+)", lambda m: "" if m.group(1).lower() in generic else m.group(0), d)
print(re.sub(r"[ \t]+\n", "\n", d).strip())
