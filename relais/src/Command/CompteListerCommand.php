<?php

namespace App\Command;

use App\Repository\CompteRepository;
use App\Repository\DepotRepository;
use Symfony\Component\Console\Attribute\AsCommand;
use Symfony\Component\Console\Command\Command;
use Symfony\Component\Console\Input\InputInterface;
use Symfony\Component\Console\Output\OutputInterface;
use Symfony\Component\Console\Style\SymfonyStyle;

#[AsCommand(name: 'app:compte:lister', description: 'Liste les comptes et leurs fichiers en attente')]
class CompteListerCommand extends Command
{
    public function __construct(private CompteRepository $comptes, private DepotRepository $depots)
    {
        parent::__construct();
    }

    protected function execute(InputInterface $input, OutputInterface $output): int
    {
        $lignes = [];
        foreach ($this->comptes->findBy([], ['nom' => 'ASC']) as $c) {
            $lignes[] = [$c->getNom(), $c->getCreeLe()->format('d/m/Y'), count($this->depots->enAttente($c)),
                round($this->depots->volume($c) / 1024 ** 2).' Mo'];
        }
        (new SymfonyStyle($input, $output))->table(['Compte', 'Créé le', 'En attente', 'Volume'], $lignes);

        return Command::SUCCESS;
    }
}
