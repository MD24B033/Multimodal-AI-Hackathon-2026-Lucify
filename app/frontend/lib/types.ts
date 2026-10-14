export type Locator = {
  page: number | null;
  slide: number | null;
  start_time_s: number | null;
  end_time_s: number | null;
  bbox: number[] | null;
};

export type Citation = {
  unit_id: string;
  source_id: string;
  source_title: string;
  source_kind: string;
  modality: string;
  label: string;
  locator: Locator;
  excerpt: string;
  score: number;
  heading_path: string[];
  external_url: string | null;
  has_image: boolean;
  marker?: number;
};

export type Profile = {
  id: string;
  name: string;
  description: string | null;
  accent: "iris" | "cyan" | "mint" | "amber" | "rose";
  is_default: boolean;
  course_count: number;
  created_at: string;
};

export type Course = {
  id: string;
  profile_id: string | null;
  title: string;
  description: string | null;
  exam_date: string | null;
  created_at: string;
  unit_count: number;
  source_count: number;
  ready_source_count: number;
  topic_count: number;
  concept_count: number;
  modalities: Record<string, number>;
};

export type IngestionJob = {
  status: string;
  stage: string;
  progress: number;
  detail: Record<string, unknown>;
  error: string | null;
};

export type Source = {
  id: string;
  course_id: string;
  kind: string;
  status: string;
  title: string;
  original_filename: string | null;
  external_url: string | null;
  page_count: number | null;
  duration_seconds: number | null;
  error: string | null;
  meta: Record<string, unknown>;
  created_at: string;
  job?: IngestionJob;
};

export type Topic = {
  id: string;
  name: string;
  kind: string;
  parent_id: string | null;
  summary: string | null;
  concepts: string[];
};

export type FlowNode = {
  id: string;
  name: string;
  kind: string;
  summary: string | null;
  parent_id: string | null;
  children: string[];
  layer: number;
  unit_count: number;
  concept_count: number;
  mastery: number | null;
  attempts: number;
};

export type FlowEdge = {
  source: string;
  target: string;
  rationale: string | null;
  kind: string;
};

export type FlowMap = {
  nodes: FlowNode[];
  edges: FlowEdge[];
  layers: number;
};

export type Student = {
  id: string;
  name: string;
  email: string | null;
  preferred_language: string;
  onboarded_at: string | null;
  is_simulated: boolean;
  meta: Record<string, unknown>;
};

export type ChatMessage = {
  id: string;
  role: "user" | "assistant";
  content: string;
  citations: Citation[];
  grounding_status: "grounded" | "partial" | "unsupported" | "refused" | null;
  coverage: number | null;
  outside_knowledge: string | null;
  language: string;
  audio_url: string | null;
  latency_ms: number | null;
  created_at: string;
};

export type ChatSession = {
  id: string;
  course_id: string;
  student_id: string;
  title: string;
  messages?: ChatMessage[];
};

export type AskResponse = {
  user_message: ChatMessage;
  message: ChatMessage;
  followups: string[];
  unsupported_claims: string[];
};

export type Question = {
  id: string;
  qtype: "mcq" | "short_answer" | "numerical";
  stem: string;
  options: string[] | null;
  difficulty: string;
  topic_id: string | null;
  citations: Citation[];
  verified: boolean;
  answer_units: string | null;
  answer_key?: string;
  answer_explanation?: string;
  verification?: Record<string, unknown>;
};

export type AssessmentItem = {
  id: string;
  ordinal: number;
  question: Question;
  response: string | null;
  is_correct?: boolean | null;
  score?: number | null;
  feedback?: string | null;
  feedback_citations?: Citation[];
  misconception?: string | null;
};

export type Assessment = {
  id: string;
  course_id: string;
  student_id: string;
  title: string;
  kind: string;
  status: string;
  scope: Record<string, unknown>;
  adaptive: boolean;
  created_at: string;
  submitted_at: string | null;
  items?: AssessmentItem[];
  question_count?: number;
  generation?: {
    requested: number;
    generated: number;
    rejected_duplicate: number;
    rejected_verification: number;
    topics_covered: string[];
    verification_issues: string[];
  };
};

export type AssessmentReport = {
  id: string;
  assessment_id: string;
  summary: string;
  score_percent: number;
  weak_topics: { topic_id: string; topic: string; accuracy: number; questions: number; mastery: number }[];
  strong_topics: { topic_id: string; topic: string; accuracy: number; questions: number; mastery: number }[];
  misconceptions: { topic: string; misconception: string; evidence: string; correction: string }[];
  recommendations: { action: string; topic: string; reason: string }[];
  mastery_delta: { topic_id: string; topic: string; before: number; after: number; delta: number }[];
  created_at: string;
};

export type Mastery = {
  topic_id: string;
  topic: string;
  kind: string;
  parent_id: string | null;
  mastery: number;
  theta: number;
  attempts: number;
  correct: number;
  recall: number;
  urgency: number;
  due_at: string | null;
  last_seen_at: string | null;
};

export type Dashboard = {
  student: Student;
  overall_mastery: number;
  topics_tracked: number;
  interactions: number;
  due_for_review: number;
  mastery: Mastery[];
  weak_topics: Mastery[];
  next_up: {
    topic_id: string;
    topic: string;
    mastery: number;
    layer: number;
    blocked_by: string[];
    priority: number;
  }[];
  mastery_history: { date: string; mastery: number; events: number }[];
  recent_assessments: {
    id: string;
    title: string;
    kind: string;
    status: string;
    created_at: string;
    score_percent: number | null;
  }[];
};

export type StudyPlan = {
  id: string;
  exam_date: string;
  daily_minutes: number;
  sessions: {
    date: string;
    topic_id: string;
    topic: string;
    minutes: number;
    activity: string;
    reason: string;
  }[];
  rationale: string | null;
  created_at: string;
};

export type Flashcard = {
  id: string;
  front: string;
  back?: string;
  topic_id: string | null;
  citations: Citation[];
  due_at: string | null;
  repetitions: number;
  interval_days: number;
};

export type EvalRun = {
  id: string;
  name: string;
  kind: string;
  status: string;
  config: Record<string, unknown>;
  metrics: Record<string, number | string | null | Record<string, unknown>>;
  error: string | null;
  created_at: string;
  completed_at: string | null;
  detail?: Record<string, unknown>;
  cases?: EvalCase[];
};

export type EvalCase = {
  id: string;
  question: string;
  expected_behavior: string;
  ground_truth: string | null;
  ground_truth_locators: { label: string; source_title: string }[];
  answer: string | null;
  retrieved_locators: { label: string; source_title: string; unit_id: string }[];
  grounding_status: string | null;
  metrics: Record<string, number | boolean | null>;
};

export type RuntimeConfig = {
  models: Record<string, string>;
  embedding_model: string;
  embedding_dimensions: number;
  retrieval: Record<string, number>;
  rate_limit: Record<string, number>;
  languages: string[];
};
