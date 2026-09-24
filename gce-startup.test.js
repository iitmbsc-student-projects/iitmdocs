import { readFileSync } from "fs";
import { join } from "path";
import { describe, expect, it } from "vitest";

const startupScript = readFileSync(join(process.cwd(), "scripts", "gce-startup.sh"), "utf-8");
const composeFile = startupScript.match(/cat > docker-compose\.yml << 'EOF'\n([\s\S]*?)\nEOF/)[1];

describe("GCE startup Compose configuration", () => {
  it("does not configure healthchecks that require curl in the service images", () => {
    expect(composeFile).toContain("  weaviate:");
    expect(composeFile).toContain("  ollama:");
    expect(composeFile).not.toContain("healthcheck:");
  });
});
