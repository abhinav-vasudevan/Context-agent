import csv


class GradeBook:
    def __init__(self):
        self._grades = {}  # name -> list of (subject, score)

    def add_student(self, name):
        if name in self._grades:
            raise ValueError(f"{name} already exists")
        self._grades[name] = []

    def add_grade(self, name, subject, score):
        if name not in self._grades:
            raise KeyError(name)
        if not 0 <= score <= 100:
            raise ValueError("score must be between 0 and 100")
        self._grades[name].append((subject, float(score)))

    def average(self, name):
        scores = [s for _, s in self._grades[name]]
        if not scores:
            raise ValueError(f"{name} has no grades")
        return sum(scores) / len(scores)

    def subject_average(self, subject):
        scores = [s for grades in self._grades.values() for subj, s in grades if subj == subject]
        if not scores:
            raise ValueError(f"no grades for {subject}")
        return sum(scores) / len(scores)

    def ranking(self):
        graded = [n for n, g in self._grades.items() if g]
        return sorted(graded, key=lambda n: (-self.average(n), n))

    def to_csv(self, path):
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["name", "subject", "score"])
            for name, grades in self._grades.items():
                for subject, score in grades:
                    writer.writerow([name, subject, score])

    @classmethod
    def from_csv(cls, path):
        book = cls()
        with open(path, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                if row["name"] not in book._grades:
                    book.add_student(row["name"])
                book.add_grade(row["name"], row["subject"], float(row["score"]))
        return book
