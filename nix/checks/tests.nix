{ inputs, ... }:
{
  perSystem =
    { pkgs, ... }:
    {
      checks.tests =
        pkgs.runCommand "tests"
          {
            nativeBuildInputs = [ pkgs.python3 ];
            src = inputs.self;
          }
          ''
            cd "$src"
            python3 -m unittest discover -s tests -v
            mkdir -p "$out"
          '';
    };
}
