export interface ToolParam {
  name: string;
  type: string;
  description: string;
  required: boolean;
}

export interface ToolInfo {
  name: string;
  description: string;
  required_role: string;
  parameters: ToolParam[];
}

export interface ConfigParam {
  key: string;
  type: string;
  description: string;
  default: unknown;
  restart_required: boolean;
}

export interface ServiceInfo {
  name: string;
  capabilities: string[];
  requires: string[];
  optional: string[];
  ai_calls: string[];
  events: string[];
  started: boolean;
  failed: boolean;
  config_namespace?: string;
  config_params: ConfigParam[];
  config_values: Record<string, unknown>;
  tools: ToolInfo[];
}
