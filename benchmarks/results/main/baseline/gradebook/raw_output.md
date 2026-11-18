### FILE: grading.py
```python
def letter_grade(score):
    if score >= 90:
        return 'A'
    elif score >= 80:
        return 'B'
    elif score >= 70:
        return 'C'
    elif score >= 60:
        return 'D'
    else:
        return 'F'
```

### FILE: gradebook.py
```python
import csv
import io
from dataclasses import dataclass
from typing import Dict, List

@dataclass
class Grade:
    name: str
    subject: str
    score: float

class GradeBook:
    def __init__(self):
        self.students: Dict[str, List[Grade]] = {}

    def add_student(self, name: str):
        if name in self.students:
            raise ValueError(f"Student '{name}' already exists")
        self.students[name] = []

    def add_grade(self, name: str, subject: str, score: float):
        if name not in self.students:
            raise KeyError(f"Unknown student '{name}'")
        if not 0 <= score <= 100:
            raise ValueError(f"Invalid score: {score}")
        self.students[name].append(Grade(name, subject, score))

    def average(self, name: str) -> float:
        if name not in self.students or not self.students[name]:
            raise ValueError(f"No grades for student '{name}'")
        return sum(g.score for g in self.students[name]) / len(self.students[name])

    def subject_average(self, subject: str) -> float:
        total = 0
        count = 0
        for student_grades in self.students.values():
            for grade in student_grades:
                if grade.subject == subject:
                    total += grade.score
                    count += 1
        if count == 0:
            raise ValueError(f"No grades for subject '{subject}'")
        return total / count

    def ranking(self) -> List[str]:
        students = [(name, self.average(name)) for name in self.students if self.students[name]]
        students.sort(key=lambda x: (-x[1], x[0]))
        return [name for name, _ in students]

    @classmethod
    def from_csv(cls, path: str) -> 'GradeBook':
        with open(path, 'r') as f:
            reader = csv.reader(f)
            students = {}
            for row in reader:
                name, subject, score = row
                if name not in students:
                    students[name] = []
                students[name].append(Grade(name, subject, float(score)))
            return cls()
```

### FILE: main.py
```python
import sys
from gradebook import GradeBook

def main():
    gradebook = GradeBook()

    while True:
        line = input().strip()
        if line == 'quit':
            break
        parts = line.split()
        if parts[0] == 'student':
            name = parts[1]
            try:
                gradebook.add_student(name)
            except ValueError as e:
                print(f"Error: {e}")
        elif parts[0] == 'grade':
            name = parts[1]
            subject = parts[2]
            score = float(parts[3])
            try:
                gradebook.add_grade(name, subject, score)
            except (KeyError, ValueError) as e:
                print(f"Error: {e}")
        elif parts[0] == 'report':
            ranking = gradebook.ranking()
            for i, name in enumerate(ranking):
                average = gradebook.average(name)
                letter = gradebook.letter_grade(average)
                print(f"{i+1}. {name} {average:.1f} {letter}")
        elif parts[0] == 'to_csv':
            path = parts[1]
            gradebook.to_csv(path)
        else:
            print("Error: unknown command")

    if gradebook.students:
        with io.StringIO() as f:
            writer = csv.writer(f)
            writer.writerow(['name', 'subject', 'score'])
            for student_grades in gradebook.students.values():
                for grade in student_grades:
                    writer.writerow([grade.name, grade.subject, grade.score])
            print(f"CSV written to standard output")

if __name__ == "__main__":
    main()
```