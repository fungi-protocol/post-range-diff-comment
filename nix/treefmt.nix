{ inputs, ... }:
{
  imports = [ inputs.treefmt-nix.flakeModule ];

  perSystem = {
    treefmt = {
      projectRootFile = "flake.nix";

      programs.nixfmt.enable = true;
      programs.ruff-check.enable = true;
      programs.ruff-format.enable = true;
      programs.shellcheck.enable = true;
      programs.shfmt.enable = true;
      programs.yamlfmt.enable = true;
    };
  };
}
