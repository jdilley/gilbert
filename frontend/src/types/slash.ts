/** Slash commands — direct tool invocation from the chat input. */

export interface SlashParameter {
  name: string;
  type: string;
  description: string;
  required: boolean;
  default: unknown;
  enum: string[] | null;
}

export interface SlashCommand {
  command: string;
  tool_name: string;
  provider: string;
  description: string;
  help: string;
  usage: string;
  required_role: string;
  parameters: SlashParameter[];
}
