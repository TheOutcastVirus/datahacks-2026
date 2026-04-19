export type GeneratedHotspotDraft = {
  id: string;
  name: string;
  aliases: string[];
  description: string;
  explainText: string;
};

export type GeneratedScenarioDraft = {
  id: string;
  label: string;
  year: number;
  riseMeters: number;
  narration: string;
  color: string;
};

export type GeneratedLocationDraft = {
  slug: string;
  name: string;
  region: string;
  description: string;
  status: string;
  updatedAt: string;
  sources: string[];
  hotspots: GeneratedHotspotDraft[];
  scenarios: GeneratedScenarioDraft[];
  defaultHotspotId: string;
  notes: string[];
  orthogonalWorkflow: string[];
  exportChecklist: string[];
};

export type LocationOnboardingResponse = {
  draft: GeneratedLocationDraft;
  locationRecordSnippet: string;
  orthogonalSearchSummary: {
    skillSearch: string;
    apiSearch: string;
  };
  caveat: string;
};

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
