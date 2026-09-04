/**
 * Genera `src/lib/api-schema.ts` a partir del esquema OpenAPI del backend.
 *
 * El contrato de la API se escribe una sola vez, en los modelos Pydantic. Aquí
 * lo traemos a TypeScript para que `tsc` avise si el frontend se desincroniza
 * del backend, en vez de descubrirlo en tiempo de ejecución.
 *
 *   npm run gen:api
 */

import { execFileSync } from "node:child_process";
import { existsSync, mkdirSync, writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import openapiTS, { astToString } from "openapi-typescript";

const aqui = dirname(fileURLToPath(import.meta.url));
const raizProyecto = resolve(aqui, "..", "..");
const destino = resolve(aqui, "..", "src", "lib", "api-schema.ts");

function interpreteDePython() {
  // `bin` en POSIX, `Scripts` en Windows: el venv del repo sirve en ambos.
  for (const relativo of [
    [".venv", "bin", "python"],
    [".venv", "Scripts", "python.exe"],
  ]) {
    const candidato = resolve(raizProyecto, ...relativo);
    if (existsSync(candidato)) return candidato;
  }
  return process.env.PYTHON ?? "python3";
}

const python = interpreteDePython();
process.stderr.write(`Pidiendo el esquema OpenAPI a ${python}…\n`);

const crudo = execFileSync(python, ["-m", "homelab_dashboard.cli", "openapi"], {
  cwd: raizProyecto,
  encoding: "utf8",
  stdio: ["ignore", "pipe", "inherit"],
  maxBuffer: 32 * 1024 * 1024,
});

const ast = await openapiTS(JSON.parse(crudo), {
  alphabetize: true,
  emptyObjectsUnknown: true,
});

const cabecera = `/* eslint-disable */
/**
 * ARCHIVO GENERADO. No lo edites a mano.
 *
 * Origen: esquema OpenAPI de FastAPI.
 * Regenerar con: npm run gen:api
 */

`;

mkdirSync(dirname(destino), { recursive: true });
writeFileSync(destino, cabecera + astToString(ast), "utf8");
process.stderr.write(`Tipos escritos en ${destino}\n`);
