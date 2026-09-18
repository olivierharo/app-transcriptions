<?php

namespace App\Repository;

use App\Entity\Compte;
use App\Entity\Depot;
use Doctrine\Bundle\DoctrineBundle\Repository\ServiceEntityRepository;
use Doctrine\Persistence\ManagerRegistry;

/** @extends ServiceEntityRepository<Depot> */
class DepotRepository extends ServiceEntityRepository
{
    public function __construct(ManagerRegistry $registry)
    {
        parent::__construct($registry, Depot::class);
    }

    /** @return Depot[] */
    public function enAttente(Compte $compte): array
    {
        return $this->findBy(['compte' => $compte], ['dateDepot' => 'ASC']);
    }

    public function volume(Compte $compte): int
    {
        return (int) $this->createQueryBuilder('d')
            ->select('COALESCE(SUM(d.taille), 0)')
            ->where('d.compte = :c')->setParameter('c', $compte)
            ->getQuery()->getSingleScalarResult();
    }

    /** @return Depot[] */
    public function plusAnciensQue(\DateTimeImmutable $limite): array
    {
        return $this->createQueryBuilder('d')
            ->where('d.dateDepot < :l')->setParameter('l', $limite)
            ->getQuery()->getResult();
    }
}
