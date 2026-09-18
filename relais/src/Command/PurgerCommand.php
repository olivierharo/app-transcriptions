<?php

namespace App\Command;

use App\Repository\DepotRepository;
use App\Service\Boites;
use Symfony\Component\Console\Attribute\AsCommand;
use Symfony\Component\Console\Command\Command;
use Symfony\Component\Console\Input\InputInterface;
use Symfony\Component\Console\Output\OutputInterface;
use Symfony\Component\DependencyInjection\Attribute\Autowire;

/**
 * A lancer chaque nuit par cron : supprime les depots jamais releves et les
 * envois interrompus (fichiers .part).
 */
#[AsCommand(name: 'app:purger', description: 'Supprime les dépôts jamais récupérés et les envois interrompus')]
class PurgerCommand extends Command
{
    public function __construct(
        private DepotRepository $depots,
        private Boites $boites,
        #[Autowire('%env(int:RELAIS_CONSERVATION_JOURS)%')] private int $jours,
        #[Autowire('%kernel.project_dir%/var/boites')] private string $racine,
    ) {
        parent::__construct();
    }

    protected function execute(InputInterface $input, OutputInterface $output): int
    {
        $n = 0;
        foreach ($this->depots->plusAnciensQue(new \DateTimeImmutable("-{$this->jours} days")) as $depot) {
            $this->boites->supprimer($depot);
            ++$n;
        }
        foreach (glob($this->racine.'/*/*.part') ?: [] as $partiel) {
            if (filemtime($partiel) < time() - 3600) {
                unlink($partiel);
                ++$n;
            }
        }
        $output->writeln("$n élément(s) purgé(s).");

        return Command::SUCCESS;
    }
}
