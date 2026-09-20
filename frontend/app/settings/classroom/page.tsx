"use client";

import { Suspense, useCallback, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { ClassroomPanel } from "@/components/ClassroomPanel";
import { useMe } from "@/components/MeContext";
import { api, ApiError, type Classroom, type Experiment } from "@/lib/api";

const STORAGE_KEY = "labtutor:active-classroom-id";

function ClassroomSettings() {
  const me = useMe();
  const router = useRouter();
  const params = useSearchParams();
  const [classrooms, setClassrooms] = useState<Classroom[]>([]);
  const [experiments, setExperiments] = useState<Experiment[]>([]);
  const [selectedId, setSelectedId] = useState("");
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    try {
      // Admin sees every class, faculty their own, and a student promoted to
      // co-faculty only the classes where that applies.
      let list: Classroom[];
      if (me.role === "admin") {
        list = (await api.get<{ classrooms: Classroom[] }>("/api/classrooms")).classrooms;
      } else if (me.role === "faculty") {
        list = (await api.get<{ classrooms: Classroom[] }>("/api/classrooms/mine")).classrooms;
      } else {
        list = (await api.get<{ classrooms: Classroom[] }>("/api/classrooms/enrolled")).classrooms.filter(
          (c) => c.co_faculty,
        );
      }
      setClassrooms(list);
      const wanted = params.get("classroom") || localStorage.getItem(STORAGE_KEY) || "";
      setSelectedId((current) => {
        const keep = current && list.some((c) => c.id === current) ? current : "";
        return keep || (list.some((c) => c.id === wanted) ? wanted : list[0]?.id || "");
      });
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    } finally {
      setLoaded(true);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [me.role]);

  useEffect(() => {
    load();
    api
      .get<{ experiments: Experiment[] }>("/api/classrooms/experiments")
      .then((res) => setExperiments(res.experiments))
      .catch(() => undefined);
  }, [load]);

  const choose = (id: string) => {
    setSelectedId(id);
    try {
      localStorage.setItem(STORAGE_KEY, id);
    } catch {
      // storage can be unavailable; the URL still carries the choice
    }
    router.replace(`/settings/classroom?classroom=${encodeURIComponent(id)}`);
  };

  const classroom = classrooms.find((c) => c.id === selectedId);

  return (
    <div className="page">
      <h2 className="page-title">Classroom</h2>
      {error && <div className="error">{error}</div>}
      {loaded && classrooms.length === 0 && !error && (
        <p className="muted">
          You have no classrooms yet. Create one from the chat screen with "Create Classroom Section".
        </p>
      )}
      {classrooms.length > 0 && (
        <div className="toolbar">
          <div className="field">
            <label className="muted" htmlFor="classroom-select">
              Classroom
            </label>
            <select id="classroom-select" value={selectedId} onChange={(e) => choose(e.target.value)}>
              {classrooms.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name}
                </option>
              ))}
            </select>
          </div>
        </div>
      )}
      {classroom && (
        <ClassroomPanel
          key={classroom.id}
          classroom={classroom}
          experiments={experiments}
          onClassroomUpdated={load}
          onArchived={() => {
            setSelectedId("");
            load();
          }}
        />
      )}
    </div>
  );
}

export default function ClassroomSettingsPage() {
  return (
    <Suspense fallback={null}>
      <ClassroomSettings />
    </Suspense>
  );
}
