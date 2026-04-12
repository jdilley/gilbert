import { useState } from "react";
import type { ServiceInfo } from "@/types/system";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";

interface ServiceCardProps {
  service: ServiceInfo;
}

export function ServiceCard({ service }: ServiceCardProps) {
  const [expanded, setExpanded] = useState(false);

  return (
    <Card>
      <CardHeader
        className="cursor-pointer py-3"
        onClick={() => setExpanded(!expanded)}
      >
        <CardTitle className="text-sm flex items-center gap-2">
          <span
            className={`h-2 w-2 rounded-full ${
              service.failed
                ? "bg-red-500"
                : service.started
                  ? "bg-green-500"
                  : "bg-yellow-500"
            }`}
          />
          {service.name}
          <span className="text-xs text-muted-foreground ml-auto">
            {expanded ? "▾" : "▸"}
          </span>
        </CardTitle>
      </CardHeader>

      {expanded && (
        <CardContent className="space-y-3 text-sm pt-0">
          {service.capabilities.length > 0 && (
            <div>
              <span className="text-xs text-muted-foreground">Capabilities:</span>
              <div className="flex flex-wrap gap-1 mt-1">
                {service.capabilities.map((c) => (
                  <Badge key={c} variant="secondary" className="text-xs">
                    {c}
                  </Badge>
                ))}
              </div>
            </div>
          )}

          {service.requires.length > 0 && (
            <div>
              <span className="text-xs text-muted-foreground">Requires:</span>
              <div className="flex flex-wrap gap-1 mt-1">
                {service.requires.map((r) => (
                  <Badge key={r} variant="outline" className="text-xs">
                    {r}
                  </Badge>
                ))}
              </div>
            </div>
          )}

          {service.ai_calls.length > 0 && (
            <div>
              <span className="text-xs text-muted-foreground">AI Calls:</span>
              <div className="flex flex-wrap gap-1 mt-1">
                {service.ai_calls.map((a) => (
                  <Badge key={a} variant="outline" className="text-xs">
                    {a}
                  </Badge>
                ))}
              </div>
            </div>
          )}

          {service.events.length > 0 && (
            <div>
              <span className="text-xs text-muted-foreground">Events:</span>
              <div className="flex flex-wrap gap-1 mt-1">
                {service.events.map((e) => (
                  <Badge key={e} variant="outline" className="text-xs">
                    {e}
                  </Badge>
                ))}
              </div>
            </div>
          )}

          {service.config_params.length > 0 && (
            <div>
              <span className="text-xs text-muted-foreground">Configuration:</span>
              <div className="overflow-x-auto">
                <table className="w-full mt-1 text-xs">
                  <thead>
                    <tr className="border-b">
                      <th className="text-left py-1 pr-2">Key</th>
                      <th className="hidden sm:table-cell text-left py-1 pr-2">Type</th>
                      <th className="text-left py-1 pr-2">Value</th>
                      <th className="hidden md:table-cell text-left py-1">Default</th>
                    </tr>
                  </thead>
                  <tbody>
                    {service.config_params.map((p) => (
                      <tr key={p.key} className="border-b">
                        <td className="py-1 pr-2 break-words">{p.key}</td>
                        <td className="hidden sm:table-cell py-1 pr-2 text-muted-foreground">{p.type}</td>
                        <td className="py-1 pr-2 break-words">
                          {String(
                            service.config_values[p.key] ?? "",
                          )}
                        </td>
                        <td className="hidden md:table-cell py-1 text-muted-foreground break-words">
                          {String(p.default ?? "")}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {service.tools.length > 0 && (
            <div>
              <span className="text-xs text-muted-foreground">
                Tools ({service.tools.length}):
              </span>
              <div className="mt-1 space-y-1">
                {service.tools.map((t) => (
                  <div key={t.name} className="border rounded-md px-2 py-1">
                    <div className="flex items-center gap-2">
                      <span className="font-medium">{t.name}</span>
                      <Badge variant="outline" className="text-[10px]">
                        {t.required_role}
                      </Badge>
                    </div>
                    <p className="text-muted-foreground text-xs">
                      {t.description}
                    </p>
                  </div>
                ))}
              </div>
            </div>
          )}
        </CardContent>
      )}
    </Card>
  );
}
