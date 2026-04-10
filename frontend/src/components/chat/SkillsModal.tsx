import { useState, useEffect, useMemo, useCallback } from "react";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Separator } from "@/components/ui/separator";
import { useWsApi } from "@/hooks/useWsApi";
import type { SkillInfo } from "@/types/skills";

interface SkillsModalProps {
  open: boolean;
  conversationId: string | null;
  onClose: () => void;
}

export function SkillsModal({ open, conversationId, onClose }: SkillsModalProps) {
  const api = useWsApi();
  const [skills, setSkills] = useState<SkillInfo[]>([]);
  const [activeSkills, setActiveSkills] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [toggling, setToggling] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    setLoading(true);

    const promises: Promise<void>[] = [
      api.listSkills().then(setSkills),
    ];
    if (conversationId) {
      promises.push(
        api.getConversationSkills(conversationId).then(setActiveSkills),
      );
    } else {
      setActiveSkills([]);
    }

    Promise.all(promises).finally(() => setLoading(false));
  }, [open, conversationId, api]);

  const { globalSkills, userSkills } = useMemo(() => {
    const global = skills.filter((s) => s.scope === "global").sort((a, b) => a.name.localeCompare(b.name));
    const user = skills.filter((s) => s.scope === "user").sort((a, b) => a.name.localeCompare(b.name));
    return { globalSkills: global, userSkills: user };
  }, [skills]);

  const handleToggle = useCallback(
    async (skillName: string) => {
      if (!conversationId || toggling) return;
      setToggling(skillName);
      const enabled = !activeSkills.includes(skillName);
      try {
        const result = await api.toggleConversationSkill(conversationId, skillName, enabled);
        setActiveSkills(result.active_skills);
      } finally {
        setToggling(null);
      }
    },
    [conversationId, activeSkills, toggling, api],
  );

  function renderSkill(skill: SkillInfo) {
    const isActive = activeSkills.includes(skill.key);
    const isToggling = toggling === skill.key;
    return (
      <label
        key={skill.key}
        className="flex items-start gap-2.5 rounded-lg px-2 py-1.5 cursor-pointer hover:bg-accent transition-colors"
      >
        <input
          type="checkbox"
          checked={isActive}
          disabled={isToggling || !conversationId}
          onChange={() => handleToggle(skill.key)}
          className="rounded border-input mt-0.5"
        />
        <div className="min-w-0 flex-1">
          <span className="text-sm font-medium">{skill.name}</span>
          <p className="text-xs text-muted-foreground line-clamp-2">
            {skill.description}
          </p>
        </div>
      </label>
    );
  }

  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Skills</DialogTitle>
        </DialogHeader>
        {loading ? (
          <p className="text-sm text-muted-foreground py-4 text-center">
            Loading skills...
          </p>
        ) : skills.length === 0 ? (
          <p className="text-sm text-muted-foreground py-4 text-center">
            No skills available
          </p>
        ) : !conversationId ? (
          <p className="text-sm text-muted-foreground py-4 text-center">
            Start a conversation to enable skills
          </p>
        ) : (
          <ScrollArea className="h-[300px] -mx-1">
            <div className="px-1">
              {globalSkills.length > 0 && (
                <div className="mb-2">
                  {userSkills.length > 0 && (
                    <h3 className="text-xs font-medium text-muted-foreground uppercase tracking-wider px-2 mb-1">
                      Global Skills
                    </h3>
                  )}
                  {globalSkills.map(renderSkill)}
                </div>
              )}

              {globalSkills.length > 0 && userSkills.length > 0 && (
                <Separator className="my-2" />
              )}

              {userSkills.length > 0 && (
                <div className="mb-2">
                  <h3 className="text-xs font-medium text-muted-foreground uppercase tracking-wider px-2 mb-1">
                    Your Skills
                  </h3>
                  {userSkills.map(renderSkill)}
                </div>
              )}
            </div>
          </ScrollArea>
        )}
      </DialogContent>
    </Dialog>
  );
}
