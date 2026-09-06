from functools import dataclass
from jinja2 import Template
from jobagent.prompts.schemas import JobAnalysis, FitAssessment

@dataclass(frozen=True)
class Prompt:
    agent : str
    version : str
    hash : str
    body : str
    variables : frozenset[str]
    output_schema : JobAnalysis | FitAssessment

    @property
    def key(self) -> str : 
        return f"{self.agent}/{self.version}"

    def render(self, **kwargs) -> str:
        return Template(self.body).render(**kwargs)