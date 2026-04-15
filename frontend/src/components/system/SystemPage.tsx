import { useQuery } from "@tanstack/react-query";
import { useWsApi } from "@/hooks/useWsApi";
import { useWebSocket } from "@/hooks/useWebSocket";
import { ServiceCard } from "./ServiceCard";

export function SystemPage() {
  const api = useWsApi();
  const { connected } = useWebSocket();
  const { data, isLoading } = useQuery({
    queryKey: ["system-services"],
    queryFn: api.listServices,
    enabled: connected,
  });

  if (isLoading) {
    return <div className="p-4 sm:p-6 text-muted-foreground">Loading...</div>;
  }

  return (
    <div className="p-4 sm:p-6 space-y-4 max-w-4xl mx-auto">
      <div className="space-y-3">
        {data?.services.map((svc) => (
          <ServiceCard key={svc.name} service={svc} />
        ))}
      </div>
    </div>
  );
}
