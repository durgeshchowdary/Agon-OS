'use client';

import { useState, useEffect, useRef, useCallback } from 'react';
import { useRouter, useParams } from 'next/navigation';
import {
  ArrowLeft,
  Bot,
  Code,
  Loader2,
  Play,
  Sparkles,
  User,
  Check,
  X,
} from 'lucide-react';
import { AgentRun, AgentStep, Project } from '@/types';

const API = 'http://127.0.0.1:8000';

const AGENT_COLORS: Record<string, string> = {
  PM: 'text-emerald-400 bg-emerald-950/40 border-emerald-500/30',
  Architect: 'text-blue-400 bg-blue-950/40 border-blue-500/30',
  System: 'text-red-400 bg-red-950/40 border-red-500/30',
};

export default function ProjectPage() {
  const router = useRouter();
  const params = useParams();
  const projectId = params.id as string;

  const [project, setProject] = useState<Project | null>(null);
  const [loading, setLoading] = useState(true);
  const [prompt, setPrompt] = useState('');
  const [runStatus, setRunStatus] = useState<'idle' | 'running' | 'completed' | 'failed' | 'waiting_approval'>('idle');
  const [currentStage, setCurrentStage] = useState<string | null>(null);
  const [steps, setSteps] = useState<AgentStep[]>([]);
  const [error, setError] = useState('');
  const [activeRunId, setActiveRunId] = useState<string | null>(null);

  // Approval form state
  const [comments, setComments] = useState('');
  const [rationale, setRationale] = useState('');
  const [actionLoading, setActionLoading] = useState(false);

  const streamRef = useRef<EventSource | null>(null);
  const streamEndRef = useRef<HTMLDivElement>(null);

  const getToken = () => localStorage.getItem('agon_token');

  const fetchRunDetails = useCallback(async (runId: string) => {
    const token = getToken();
    if (!token) return;
    try {
      const res = await fetch(`${API}/api/v1/runs/${runId}`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (res.ok) {
        const detail = await res.json();
        setSteps(detail.steps || []);
        setPrompt(detail.initial_prompt);
        if (detail.status === 'COMPLETED') {
          setRunStatus('completed');
        } else if (detail.status === 'FAILED') {
          setRunStatus('failed');
        } else if (detail.status === 'WAITING_APPROVAL') {
          setRunStatus('waiting_approval');
          setCurrentStage(detail.current_stage || null);
        } else if (detail.status === 'RUNNING') {
          setRunStatus('running');
          setCurrentStage(detail.current_stage || null);
        } else if (detail.status === 'PENDING') {
          setRunStatus('running');
          setCurrentStage(null);
        }
      }
    } catch (err) {
      console.error('Failed to fetch run details:', err);
    }
  }, []);

  const connectStream = useCallback((runId: string) => {
    if (streamRef.current) {
      streamRef.current.close();
    }

    const es = new EventSource(`${API}/api/v1/runs/${runId}/stream`);
    streamRef.current = es;

    es.onmessage = (event) => {
      const data = JSON.parse(event.data);

      if (data.status === 'COMPLETED') {
        setRunStatus('completed');
        fetchRunDetails(runId);
        es.close();
        streamRef.current = null;
        return;
      }

      if (data.status === 'FAILED') {
        setRunStatus('failed');
        setError(data.error || 'Run failed');
        fetchRunDetails(runId);
        es.close();
        streamRef.current = null;
        return;
      }

      if (data.status === 'WAITING_APPROVAL') {
        setRunStatus('waiting_approval');
        setCurrentStage(data.current_stage || null);
        fetchRunDetails(runId);
      }

      if (data.status === 'APPROVAL_REQUIRED') {
        setRunStatus('waiting_approval');
        setCurrentStage(data.stage || null);
        fetchRunDetails(runId);
      }

      if (data.status === 'WORKFLOW_RESUMED') {
        setRunStatus('running');
        setCurrentStage(data.stage || null);
        fetchRunDetails(runId);
      }

      if (data.id && data.agent_name) {
        setSteps((prev) => {
          if (prev.some((s) => s.id === data.id)) return prev;
          return [...prev, data as AgentStep];
        });
      }
    };

    es.onerror = () => {
      if (runStatus !== 'completed' && runStatus !== 'waiting_approval') {
        es.close();
        streamRef.current = null;
      }
    };
  }, [runStatus, fetchRunDetails]);

  useEffect(() => {
    const token = getToken();
    if (!token) {
      router.push('/login');
      return;
    }

    const loadProject = async () => {
      try {
        const res = await fetch(`${API}/api/v1/projects/${projectId}`, {
          headers: { Authorization: `Bearer ${token}` },
        });
        if (!res.ok) {
          router.push('/dashboard');
          return;
        }
        const proj = await res.json();
        setProject(proj);

        const runsRes = await fetch(`${API}/api/v1/projects/${projectId}/runs`, {
          headers: { Authorization: `Bearer ${token}` },
        });
        if (runsRes.ok) {
          const runs: AgentRun[] = await runsRes.json();
          const activeRun = runs.find(
            (r) => r.status === 'RUNNING' || r.status === 'PENDING' || r.status === 'WAITING_APPROVAL'
          );
          if (activeRun) {
            setActiveRunId(activeRun.id);
            setPrompt(activeRun.initial_prompt);
            if (activeRun.status === 'WAITING_APPROVAL') {
              setRunStatus('waiting_approval');
              setCurrentStage(activeRun.current_stage || null);
            } else {
              setRunStatus('running');
            }
            connectStream(activeRun.id);
            fetchRunDetails(activeRun.id);
          } else if (runs.length > 0) {
            setActiveRunId(runs[0].id);
            fetchRunDetails(runs[0].id);
          }
        }
      } catch {
        setError('Failed to load project. Is the backend running?');
      } finally {
        setLoading(false);
      }
    };

    loadProject();

    return () => {
      if (streamRef.current) {
        streamRef.current.close();
      }
    };
  }, [projectId, router, connectStream, fetchRunDetails]);

  useEffect(() => {
    streamEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [steps]);

  const handleRun = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!prompt.trim()) return;

    const token = getToken();
    if (!token) return;

    setError('');
    setSteps([]);
    setRunStatus('running');

    try {
      const res = await fetch(`${API}/api/v1/projects/${projectId}/runs`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({ initial_prompt: prompt.trim() }),
      });

      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || 'Failed to start run');
      }

      const run: AgentRun = await res.json();
      setActiveRunId(run.id);
      connectStream(run.id);
    } catch (err: unknown) {
      setRunStatus('failed');
      setError(err instanceof Error ? err.message : 'Something went wrong');
    }
  };

  const handleApprove = async () => {
    if (!activeRunId || !currentStage) return;
    const token = getToken();
    if (!token) return;
    setActionLoading(true);
    setError('');
    try {
      const res = await fetch(`${API}/api/v1/runs/${activeRunId}/approve`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({
          stage: currentStage,
          comments: comments.trim() || undefined,
          rationale: rationale.trim() || undefined,
        }),
      });
      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || 'Failed to approve stage');
      }
      setComments('');
      setRationale('');
      setRunStatus('running');
      connectStream(activeRunId);
      await fetchRunDetails(activeRunId);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Failed to approve stage');
    } finally {
      setActionLoading(false);
    }
  };

  const handleReject = async () => {
    if (!activeRunId || !currentStage) return;
    const token = getToken();
    if (!token) return;
    setActionLoading(true);
    setError('');
    try {
      const res = await fetch(`${API}/api/v1/runs/${activeRunId}/reject`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({
          stage: currentStage,
          comments: comments.trim() || undefined,
          rationale: rationale.trim() || undefined,
        }),
      });
      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || 'Failed to reject stage');
      }
      setComments('');
      setRationale('');
      connectStream(activeRunId);
      await fetchRunDetails(activeRunId);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Failed to reject stage');
    } finally {
      setActionLoading(false);
    }
  };


  if (loading) {
    return (
      <div className="min-h-screen bg-[#030712] flex items-center justify-center">
        <Loader2 className="w-8 h-8 text-indigo-400 animate-spin" />
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-[#030712] flex flex-col text-gray-200">
      <header className="border-b border-white/5 bg-[#070b19] px-6 py-4 flex items-center justify-between sticky top-0 z-40">
        <div className="flex items-center gap-4">
          <button
            onClick={() => router.push('/dashboard')}
            className="p-2 rounded-lg bg-gray-900 border border-white/5 text-gray-400 hover:text-white transition cursor-pointer"
          >
            <ArrowLeft className="w-4 h-4" />
          </button>
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 rounded-lg bg-gradient-to-tr from-indigo-600 to-purple-600 flex items-center justify-center border border-indigo-400/20">
              <Code className="w-5 h-5 text-white" />
            </div>
            <div>
              <span className="font-extrabold tracking-tight text-white">{project?.name || 'Project'}</span>
              <span className="text-xs text-gray-500 ml-2">{project?.domain?.replace('_', ' ')}</span>
            </div>
          </div>
        </div>

        <div className="flex items-center gap-3">
          {runStatus === 'running' && (
            <span className="inline-flex items-center gap-2 px-3 py-1.5 rounded-full bg-indigo-950/50 border border-indigo-500/30 text-xs text-indigo-300">
              <Loader2 className="w-3 h-3 animate-spin" />
              Agents running...
            </span>
          )}
          {runStatus === 'waiting_approval' && (
            <span className="inline-flex items-center gap-2 px-3 py-1.5 rounded-full bg-amber-950/50 border border-amber-500/30 text-xs text-amber-300 font-medium">
              <Loader2 className="w-3 h-3 animate-pulse" />
              Approval required ({currentStage})
            </span>
          )}
          {runStatus === 'completed' && (
            <span className="inline-flex items-center gap-2 px-3 py-1.5 rounded-full bg-emerald-950/50 border border-emerald-500/30 text-xs text-emerald-300">
              <Sparkles className="w-3 h-3" />
              Run complete
            </span>
          )}
        </div>
      </header>

      <main className="flex-1 max-w-4xl w-full mx-auto px-6 py-8 flex flex-col gap-6">
        {project?.description && (
          <p className="text-sm text-gray-400">{project.description}</p>
        )}

        <form onSubmit={handleRun} className="glass-panel rounded-xl p-5 border border-white/5">
          <label className="block text-xs font-semibold text-gray-400 uppercase tracking-wider mb-2">
            Software Idea / Prompt
          </label>
          <textarea
            value={prompt}
            onChange={(e) => setPrompt(e.target.value)}
            disabled={runStatus === 'running' || runStatus === 'waiting_approval'}
            placeholder="Describe your software idea... e.g. Build a GST filing platform for small businesses"
            rows={3}
            className="w-full px-4 py-3 rounded-lg bg-gray-900/60 border border-white/10 text-white placeholder-gray-600 focus:outline-none focus:border-indigo-500 transition text-sm resize-none disabled:opacity-50"
          />
          {error && (
            <div className="mt-3 p-2.5 rounded bg-red-950/40 border border-red-500/20 text-red-300 text-xs">
              {error}
            </div>
          )}
          <div className="mt-4 flex justify-end">
            <button
              type="submit"
              disabled={runStatus === 'running' || runStatus === 'waiting_approval' || !prompt.trim()}
              className="inline-flex items-center gap-2 px-5 py-2.5 rounded-lg bg-indigo-600 hover:bg-indigo-500 disabled:bg-indigo-800 disabled:opacity-50 text-white font-medium text-sm transition cursor-pointer"
            >
              {runStatus === 'running' ? (
                <>
                  <Loader2 className="w-4 h-4 animate-spin" />
                  Running PM + Architect...
                </>
              ) : (
                <>
                  <Play className="w-4 h-4" />
                  Run Agents
                </>
              )}
            </button>
          </div>
        </form>

        {runStatus === 'waiting_approval' && (
          <div className="glass-panel rounded-xl p-6 border border-amber-500/20 bg-amber-950/10 flex flex-col gap-4 animate-in fade-in duration-300">
            <div className="flex items-center gap-3 border-b border-white/5 pb-3">
              <Bot className="w-5 h-5 text-amber-400 animate-pulse" />
              <div>
                <h3 className="text-sm font-bold text-white">Approval Gate: {currentStage} Completed</h3>
                <p className="text-xs text-gray-400">Review the generated draft outputs in the stream below before advancing the workflow.</p>
              </div>
            </div>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div>
                <label className="block text-[10px] font-semibold text-gray-400 uppercase tracking-wider mb-1.5">
                  Reviewer Comments
                </label>
                <textarea
                  value={comments}
                  onChange={(e) => setComments(e.target.value)}
                  disabled={actionLoading}
                  placeholder="Provide general comments or suggestions..."
                  rows={3}
                  className="w-full px-3 py-2 rounded-lg bg-gray-900 border border-white/10 text-white placeholder-gray-600 focus:outline-none focus:border-amber-500 transition text-xs resize-none disabled:opacity-50"
                />
              </div>
              <div>
                <label className="block text-[10px] font-semibold text-gray-400 uppercase tracking-wider mb-1.5">
                  Approval / Rejection Rationale
                </label>
                <textarea
                  value={rationale}
                  onChange={(e) => setRationale(e.target.value)}
                  disabled={actionLoading}
                  placeholder="e.g. Requirements are complete and acceptable..."
                  rows={3}
                  className="w-full px-3 py-2 rounded-lg bg-gray-900 border border-white/10 text-white placeholder-gray-600 focus:outline-none focus:border-amber-500 transition text-xs resize-none disabled:opacity-50"
                />
              </div>
            </div>
            <div className="flex justify-end gap-3 pt-2">
              <button
                type="button"
                onClick={handleReject}
                disabled={actionLoading}
                className="inline-flex items-center gap-1.5 px-4 py-2 rounded-lg border border-red-500/30 bg-red-950/10 hover:bg-red-950/30 text-red-400 text-xs font-semibold transition cursor-pointer disabled:opacity-50"
              >
                <X className="w-3.5 h-3.5" />
                Reject Stage
              </button>
              <button
                type="button"
                onClick={handleApprove}
                disabled={actionLoading}
                className="inline-flex items-center gap-1.5 px-4 py-2 rounded-lg bg-emerald-600 hover:bg-emerald-500 text-white text-xs font-semibold transition cursor-pointer disabled:opacity-50"
              >
                <Check className="w-3.5 h-3.5" />
                Approve & Proceed
              </button>
            </div>
          </div>
        )}

        <div className="flex-1 glass-panel rounded-xl border border-white/5 flex flex-col min-h-[400px]">
          <div className="px-5 py-4 border-b border-white/5 flex items-center gap-2">
            <Bot className="w-4 h-4 text-indigo-400" />
            <h2 className="text-sm font-bold text-white">Live Agent Stream</h2>
            {activeRunId && (
              <span className="text-[10px] text-gray-500 ml-auto font-mono">{activeRunId.slice(0, 8)}...</span>
            )}
          </div>

          <div className="flex-1 overflow-y-auto p-5 space-y-4">
            {steps.length === 0 && runStatus !== 'running' && (
              <div className="text-center py-16 text-gray-500 text-sm">
                Enter a prompt and click &quot;Run Agents&quot; to start PM and Architect.
              </div>
            )}

            {steps.length === 0 && runStatus === 'running' && (
              <div className="text-center py-16 text-gray-400 text-sm flex flex-col items-center gap-3">
                <Loader2 className="w-6 h-6 animate-spin text-indigo-400" />
                Waiting for agent output...
              </div>
            )}

            {steps.map((step) => {
              const colorClass = AGENT_COLORS[step.agent_name] || 'text-gray-400 bg-gray-900 border-white/10';
              const isArtifact = step.step_type === 'ARTIFACT_PROPOSAL';

              return (
                <div key={step.id} className="animate-in fade-in duration-300">
                  <div className="flex items-center gap-2 mb-2">
                    <span className={`inline-flex items-center gap-1.5 px-2 py-0.5 rounded text-[10px] font-bold uppercase tracking-wider border ${colorClass}`}>
                      {step.agent_name === 'PM' ? <User className="w-3 h-3" /> : <Bot className="w-3 h-3" />}
                      {step.agent_name}
                    </span>
                    <span className="text-[10px] text-gray-600 uppercase">{step.step_type.replace('_', ' ')}</span>
                  </div>

                  {isArtifact ? (
                    <div className="rounded-lg bg-gray-900/60 border border-white/5 p-4">
                      <pre className="text-xs text-gray-300 whitespace-pre-wrap font-mono leading-relaxed max-h-96 overflow-y-auto">
                        {step.content}
                      </pre>
                    </div>
                  ) : (
                    <p className="text-sm text-gray-400 italic pl-1">{step.content}</p>
                  )}
                </div>
              );
            })}
            <div ref={streamEndRef} />
          </div>
        </div>
      </main>
    </div>
  );
}
