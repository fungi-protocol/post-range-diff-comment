{ inputs, ... }:
{
  perSystem =
    { pkgs, ... }:
    {
      checks.actionlint =
        pkgs.runCommand "actionlint"
          {
            nativeBuildInputs = [ pkgs.actionlint ];
            src = inputs.self;
          }
          ''
            find "$src/.github/workflows" -type f \
              \( -name '*.yml' -o -name '*.yaml' \) \
              -exec actionlint {} +
            mkdir -p "$out"
          '';
    };
}
