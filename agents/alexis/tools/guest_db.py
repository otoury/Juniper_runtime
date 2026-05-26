import csv
import json

def _load_guests(self) -> list[dict]:
    if self._guest_cache is None:
        guest_file = self.workspace / "GUESTS.csv"

        if not guest_file.exists():
            self._guest_cache = []
            return self._guest_cache

        cleaned = []

        with open(guest_file, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)

            for row in reader:
                name = str(row.get("NAME", "")).strip()

                if not name:
                    continue

                if name.startswith("---"):
                    continue

                category = str(row.get("CATEGORY", "")).strip()
                expertise = str(row.get("TITLE/EXPERTISE", "")).strip()

                if not category and not expertise:
                    continue

                cleaned.append(row)

        self._guest_cache = cleaned

    return self._guest_cache

def search_guests(self, query: str) -> list[dict]:
    q_words = query.lower().split()
    matches = []

    for guest in self._load_guests():
        searchable = " ".join([
            str(guest.get("NAME", "")),
            str(guest.get("CATEGORY", "")),
            str(guest.get("TITLE/EXPERTISE", "")),
            str(guest.get("BOOKING NOTES", "")),
            str(guest.get("PARTY/AFFIL", "")),
            str(guest.get("FLAGS", "")),
        ]).lower()

        score = 0

        for word in q_words:
            if word in searchable:
                score += 1

        if score > 0:
            guest_copy = dict(guest)
            guest_copy["_score"] = score
            matches.append(guest_copy)

    matches.sort(key=lambda x: x["_score"], reverse=True)

    return matches[:8]


def build_context(self, guests: list[dict]) -> list[str]:
    if not guests:
        return []

    return [
        "GUEST CONTEXT:\n"
        + json.dumps(
            guests,
            ensure_ascii=False,
            indent=2,
        )
    ]
