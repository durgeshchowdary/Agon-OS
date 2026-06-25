export interface User {
  id: string;
  email: string;
  full_name?: string;
  created_at: string;
}

export interface Project {
  id: string;
  creator_id: string;
  name: string;
  description?: string;
  domain: string;
  created_at: string;
  updated_at: string;
}

export interface AgentRun {
  id: string;
  project_id: string;
  status: 'PENDING' | 'RUNNING' | 'COMPLETED' | 'FAILED';
  initial_prompt: string;
  started_at?: string;
  completed_at?: string;
  created_at: string;
}

export interface AgentStep {
  id: string;
  run_id: string;
  agent_name: 'PM' | 'Architect' | 'Critic' | 'CTO' | 'System';
  step_type: 'THOUGHT' | 'DEBATE' | 'ARTIFACT_PROPOSAL' | 'CRITIQUE' | 'APPROVAL';
  content: string;
  sequence_number: number;
  created_at: string;
}

export interface ProjectArtifact {
  id: string;
  project_id: string;
  run_id?: string;
  artifact_type: 'REQUIREMENTS' | 'ARCHITECTURE' | 'DATABASE' | 'API' | 'CTO_REVIEW';
  title: string;
  content: string;
  version: number;
  status: 'DRAFT' | 'APPROVED' | 'REJECTED';
  created_at: string;
  updated_at: string;
}

export interface Decision {
  id: string;
  project_id: string;
  run_id?: string;
  title: string;
  description?: string;
  options?: string[]; // Parsed from JSON list
  selected_option?: string;
  rationale?: string;
  created_at: string;
}
