'use client';

import { useState, useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { Folder, Plus, LogOut, Code, FileText, ArrowRight, User } from 'lucide-react';
import { Project } from '@/types';

export default function Dashboard() {
  const router = useRouter();
  const [projects, setProjects] = useState<Project[]>([]);
  const [loading, setLoading] = useState(true);
  const [userEmail, setUserEmail] = useState('');
  
  // Modal states
  const [showModal, setShowModal] = useState(false);
  const [projectName, setProjectName] = useState('');
  const [projectDesc, setProjectDesc] = useState('');
  const [projectDomain, setProjectDomain] = useState('software_engineering');
  const [modalLoading, setModalLoading] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    const token = localStorage.getItem('agon_token');
    if (!token) {
      router.push('/login');
      return;
    }

    const loadData = async () => {
      try {
        // Fetch User profile
        const userRes = await fetch('http://127.0.0.1:8000/api/v1/auth/me', {
          headers: { Authorization: `Bearer ${token}` },
        });
        if (userRes.ok) {
          const userData = await userRes.json();
          setUserEmail(userData.email);
        }

        // Fetch Projects
        const projectsRes = await fetch('http://127.0.0.1:8000/api/v1/projects', {
          headers: { Authorization: `Bearer ${token}` },
        });
        if (projectsRes.ok) {
          const projectsData = await projectsRes.json();
          setProjects(projectsData);
        }
      } catch (err) {
        console.error('Error loading dashboard data:', err);
      } finally {
        setLoading(false);
      }
    };

    loadData();
  }, [router]);

  const handleLogout = () => {
    localStorage.removeItem('agon_token');
    router.push('/login');
  };

  const handleCreateProject = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    setModalLoading(true);

    const token = localStorage.getItem('agon_token');
    try {
      const response = await fetch('http://127.0.0.1:8000/api/v1/projects', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({
          name: projectName,
          description: projectDesc,
          domain: projectDomain,
        }),
      });

      if (!response.ok) {
        throw new Error('Failed to create project');
      }

      const newProj = await response.json();
      setProjects((prev) => [newProj, ...prev]);
      setShowModal(false);
      
      // Clean form
      setProjectName('');
      setProjectDesc('');
      
      // Navigate straight to workspace
      router.push(`/project/${newProj.id}`);
    } catch (err: any) {
      setError(err.message || 'Something went wrong');
    } finally {
      setModalLoading(false);
    }
  };

  return (
    <div className="min-h-screen bg-[#030712] flex flex-col text-gray-200">
      {/* Top Navbar */}
      <header className="border-b border-white/5 bg-[#070b19] px-6 py-4 flex items-center justify-between sticky top-0 z-40">
        <div className="flex items-center gap-3">
          <div className="w-9 h-9 rounded-lg bg-gradient-to-tr from-indigo-600 to-purple-600 flex items-center justify-center border border-indigo-400/20">
            <Code className="w-5 h-5 text-white" />
          </div>
          <div>
            <span className="font-extrabold tracking-tight text-white">AGON OS</span>
            <span className="text-xs text-indigo-400 font-medium ml-2 uppercase px-1.5 py-0.5 rounded bg-indigo-950/50 border border-indigo-500/20">
              V1 COCKPIT
            </span>
          </div>
        </div>

        <div className="flex items-center gap-4">
          <div className="hidden sm:flex items-center gap-2 px-3 py-1.5 rounded-full bg-gray-900 border border-white/5 text-xs text-gray-300">
            <User className="w-3.5 h-3.5 text-indigo-400" />
            <span>{userEmail || 'cto@agon.ai'}</span>
          </div>
          <button
            onClick={handleLogout}
            className="p-2 rounded-lg bg-gray-900 border border-white/5 text-gray-400 hover:text-white hover:border-red-500/20 hover:bg-red-950/20 transition cursor-pointer"
            title="Sign Out"
          >
            <LogOut className="w-4 h-4" />
          </button>
        </div>
      </header>

      {/* Main Content Area */}
      <main className="flex-1 max-w-6xl w-full mx-auto px-6 py-10">
        {/* Page Header */}
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 mb-8">
          <div>
            <h1 className="text-2xl font-bold text-white tracking-tight">Your Projects</h1>
            <p className="text-sm text-gray-400 mt-1">Select a workspace or launch a new multi-agent reasoning session.</p>
          </div>
          <button
            onClick={() => setShowModal(true)}
            className="inline-flex items-center justify-center gap-2 px-4 py-2.5 rounded-lg bg-indigo-600 hover:bg-indigo-500 active:bg-indigo-700 text-white font-medium text-sm transition shadow-lg shadow-indigo-600/10 cursor-pointer"
          >
            <Plus className="w-4 h-4" />
            <span>Create Project</span>
          </button>
        </div>

        {/* Loading Skeleton */}
        {loading ? (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
            {[1, 2, 3].map((n) => (
              <div key={n} className="h-44 rounded-xl bg-gray-900/50 border border-white/5 animate-pulse"></div>
            ))}
          </div>
        ) : projects.length === 0 ? (
          /* Empty State */
          <div className="glass-panel border border-dashed border-white/10 rounded-2xl p-12 text-center max-w-lg mx-auto mt-12">
            <div className="w-12 h-12 rounded-xl bg-indigo-950/50 border border-indigo-500/25 flex items-center justify-center mx-auto mb-4">
              <Folder className="w-6 h-6 text-indigo-400" />
            </div>
            <h3 className="text-lg font-bold text-white">No projects found</h3>
            <p className="text-sm text-gray-400 mt-1.5 mb-6 max-w-xs mx-auto">
              Create a new workspace project to submit software ideas and watch specialized agents debate and design.
            </p>
            <button
              onClick={() => setShowModal(true)}
              className="px-4 py-2.5 rounded-lg bg-indigo-600 hover:bg-indigo-500 text-white text-sm font-semibold transition cursor-pointer"
            >
              Get Started
            </button>
          </div>
        ) : (
          /* Projects Grid */
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
            {projects.map((project) => (
              <div
                key={project.id}
                onClick={() => router.push(`/project/${project.id}`)}
                className="glass-card rounded-xl p-5 cursor-pointer flex flex-col justify-between group"
              >
                <div>
                  <div className="flex items-center justify-between mb-3">
                    <div className="w-8 h-8 rounded-lg bg-indigo-950/60 border border-indigo-500/30 flex items-center justify-center">
                      <Folder className="w-4 h-4 text-indigo-400" />
                    </div>
                    <span className="text-[10px] uppercase font-bold tracking-wider text-indigo-300 bg-indigo-950/40 px-2 py-0.5 rounded border border-indigo-500/10">
                      {project.domain.replace('_', ' ')}
                    </span>
                  </div>
                  <h3 className="font-bold text-white group-hover:text-indigo-400 transition truncate text-lg">
                    {project.name}
                  </h3>
                  <p className="text-xs text-gray-400 mt-1.5 line-clamp-2 min-h-[2rem]">
                    {project.description || 'No description provided.'}
                  </p>
                </div>
                <div className="mt-5 pt-4 border-t border-white/5 flex items-center justify-between text-xs text-gray-500">
                  <span>Created {new Date(project.created_at).toLocaleDateString()}</span>
                  <span className="inline-flex items-center gap-1 text-indigo-400 font-medium group-hover:translate-x-0.5 transition-transform">
                    <span>Enter</span>
                    <ArrowRight className="w-3 h-3" />
                  </span>
                </div>
              </div>
            ))}
          </div>
        )}
      </main>

      {/* Create Project Modal */}
      {showModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/80 backdrop-blur-sm">
          <div className="glass-panel w-full max-w-lg rounded-xl border border-white/10 shadow-2xl p-6 relative">
            <h3 className="text-lg font-bold text-white mb-1">Create New Workspace</h3>
            <p className="text-xs text-gray-400 mb-5">Set up the domain and configuration parameters for your software ideas.</p>

            {error && (
              <div className="mb-4 p-2.5 rounded bg-red-950/40 border border-red-500/20 text-red-300 text-xs">
                {error}
              </div>
            )}

            <form onSubmit={handleCreateProject} className="space-y-4">
              <div>
                <label className="block text-xs font-semibold text-gray-400 uppercase tracking-wider mb-1.5">
                  Project Name
                </label>
                <input
                  type="text"
                  required
                  placeholder="e.g. GST Filing Platform"
                  value={projectName}
                  onChange={(e) => setProjectName(e.target.value)}
                  className="w-full px-3 py-2 rounded bg-gray-900 border border-white/10 text-white placeholder-gray-600 focus:outline-none focus:border-indigo-500 transition text-sm"
                />
              </div>

              <div>
                <label className="block text-xs font-semibold text-gray-400 uppercase tracking-wider mb-1.5">
                  Short Description
                </label>
                <textarea
                  placeholder="What is this software idea trying to achieve?"
                  value={projectDesc}
                  onChange={(e) => setProjectDesc(e.target.value)}
                  rows={3}
                  className="w-full px-3 py-2 rounded bg-gray-900 border border-white/10 text-white placeholder-gray-600 focus:outline-none focus:border-indigo-500 transition text-sm resize-none"
                />
              </div>

              <div>
                <label className="block text-xs font-semibold text-gray-400 uppercase tracking-wider mb-1.5">
                  Target Domain
                </label>
                <select
                  value={projectDomain}
                  onChange={(e) => setProjectDomain(e.target.value)}
                  className="w-full px-3 py-2 rounded bg-gray-900 border border-white/10 text-white focus:outline-none focus:border-indigo-500 transition text-sm"
                >
                  <option value="software_engineering">Software Engineering (Default)</option>
                  <option value="legal_compliance">Legal Compliance (Upcoming)</option>
                  <option value="financial_planning">Financial Planning (Upcoming)</option>
                </select>
              </div>

              <div className="flex items-center justify-end gap-3 pt-4 border-t border-white/5">
                <button
                  type="button"
                  onClick={() => setShowModal(false)}
                  className="px-4 py-2 rounded bg-gray-900 border border-white/5 hover:bg-gray-800 text-gray-300 text-sm font-semibold transition cursor-pointer"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={modalLoading}
                  className="px-4 py-2 rounded bg-indigo-600 hover:bg-indigo-500 text-white text-sm font-semibold transition cursor-pointer"
                >
                  {modalLoading ? 'Creating...' : 'Create Project'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
