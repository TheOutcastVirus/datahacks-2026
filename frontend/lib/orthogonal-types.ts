export type ResearchBrief = {
  title: string;
  audience: string;
  executiveSummary: string;
  whyNow: string;
  evidence: string[];
  keyRisks: string[];
  stakeholders: string[];
  demoTalkingPoints: string[];
  nextActions: string[];
  exportActions: string[];
  orthogonalWorkflow: string[];
};

export type ResearchBriefResponse = {
  brief: ResearchBrief;
  orthogonalSearchSummary: {
    skillSearch: string;
    apiSearch: string;
    scrapeSummary?: string;
  };
  caveat: string;
};
