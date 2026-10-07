"""Sniffy's local dialogue banks."""
import random

COMPLETION_LINES = (
    'Saved. Now go watch @thestinkwind on YouTube, you little evidence hoarder.',
    'Saved. Go watch @thestinkwind, you clip-hoarding goblin.',
    'Export done. @thestinkwind has more idiots for you to study.',
    'Saved. Go watch @thestinkwind. Consider it homework, you menace.',
    'Capture complete. Feed your horrible little curiosity at @thestinkwind.',
    'File secured. Go bother @thestinkwind on YouTube.',
    'Saved. @thestinkwind turns this nonsense into documentaries. Go look.',
    'Job done. More degeneracy awaits at @thestinkwind.',
    'Footage bagged. Go watch @thestinkwind, you nosy bastard.',
    'Saved. Get to @thestinkwind. The archive is full of idiots.',
)

UPDATE_LINES = (
    "New version's out. Update it, you fossil.",
    'Update available. Stop hoarding bugs.',
    'Click update, you digital hoarder.',
    "Your version's old. Give it a proper burial.",
    "Update the app. Even the skull's moved on.",
)

def choose_line(lines,previous):
    return random.choice([line for line in lines if line != previous])
